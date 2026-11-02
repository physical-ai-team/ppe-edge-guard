"""HTTP API — docs/interfaces.md ① 기준.

필수 헤더는 엄격하게 검사(400/401)하고, 선택 헤더 오류는 무시 + 경고 로그로 처리한다.
ESP32는 4xx에서 재시도하지 않으므로, 선택 필드 하나 때문에 위반 사진을 잃지 않기 위해서다.
"""
import asyncio
import hmac
import json
import logging
import re
import shutil
import sqlite3
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ppe_common import db
from ppe_common.paths import image_relpath, make_event_id
from ppe_common.timeutil import parse_iso, to_iso, utcnow

from . import store
from .config import Settings
from .images import MAX_IMAGE_BYTES, InvalidImage, delete_image, inspect_jpeg, save_atomic

log = logging.getLogger("ingest.api")
router = APIRouter()

DEVICE_ID_RE = re.compile(r"^[a-z0-9-]{3,32}$")
CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
TRIGGERS = {"person", "timer", "serial", "manual"}
CLOCK_FUTURE_TOLERANCE = timedelta(hours=1)
CLOCK_MIN_VALID = datetime.fromisoformat("2024-01-01T00:00:00+00:00")  # NTP 미동기화(1970년 등) 방어
RETRY_AFTER_SEC = 30


def _error(status: int, code: str, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status, headers=headers)


def _resolve_captured_at(raw: str | None, received_at: datetime, device_id: str) -> tuple[datetime, bool]:
    """(captured_at, clock_synced). 헤더가 없거나 이상하면 received_at을 쓴다."""
    if not raw:
        return received_at, False
    try:
        captured = parse_iso(raw).replace(microsecond=0)
    except ValueError:
        log.warning("device %s: unparsable X-Captured-At %r — using received_at", device_id, raw)
        return received_at, False
    if captured - received_at > CLOCK_FUTURE_TOLERANCE or captured < CLOCK_MIN_VALID:
        log.warning("device %s: clock looks wrong (X-Captured-At=%s) — using received_at", device_id, raw)
        return received_at, False
    return captured, True


def _optional_headers(h, device_id: str) -> dict:
    trigger = h.get("x-trigger")
    if trigger and trigger not in TRIGGERS:
        log.warning("device %s: unknown X-Trigger %r ignored", device_id, trigger)
        trigger = None
    score = None
    if raw := h.get("x-detector-score"):
        try:
            score = float(raw)
            if not 0.0 <= score <= 1.0:
                raise ValueError
        except ValueError:
            log.warning("device %s: invalid X-Detector-Score %r ignored", device_id, raw)
            score = None
    firmware = (h.get("x-firmware-version") or "")[:32] or None
    return {"trigger": trigger, "detector_score": score, "firmware_version": firmware}


def _duplicate(row: sqlite3.Row) -> JSONResponse:
    return JSONResponse({"event_id": row["event_id"], "status": "duplicate"}, status_code=200)


@router.post("/api/v1/captures")
async def create_capture(request: Request):
    settings: Settings = request.app.state.settings
    h = request.headers
    device_id, token, capture_id = h.get("x-device-id"), h.get("x-device-token"), h.get("x-capture-id")

    missing = [
        name for name, value in (
            ("X-Device-Id", device_id), ("X-Device-Token", token),
            ("X-Capture-Id", capture_id), ("Content-Type", h.get("content-type")),
        ) if not value
    ]
    if missing:
        return _error(400, "missing_header", f"missing: {', '.join(missing)}")
    if not hmac.compare_digest(token.encode(), settings.device_token.encode()):
        log.warning("device %s: invalid token from %s", device_id, request.client.host if request.client else "?")
        return _error(401, "invalid_token", "X-Device-Token mismatch")
    if not DEVICE_ID_RE.fullmatch(device_id):
        return _error(400, "invalid_header", "X-Device-Id must match ^[a-z0-9-]{3,32}$")
    if not CAPTURE_ID_RE.fullmatch(capture_id):
        return _error(400, "invalid_header", "X-Capture-Id must be 1-64 chars of [A-Za-z0-9._:-]")
    if h["content-type"].split(";")[0].strip().lower() != "image/jpeg":
        return _error(400, "invalid_header", "Content-Type must be image/jpeg")

    declared = h.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        return _error(413, "payload_too_large", f"max {MAX_IMAGE_BYTES} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_IMAGE_BYTES:
            return _error(413, "payload_too_large", f"max {MAX_IMAGE_BYTES} bytes")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        width, height = inspect_jpeg(body)
    except InvalidImage as e:
        return _error(400, "invalid_image", str(e))

    db_path = db.db_path(settings.data_dir)
    with db.connect(db_path) as conn:
        if existing := store.find_by_capture(conn, device_id, capture_id):
            return _duplicate(existing)

    if shutil.disk_usage(settings.data_dir).free < settings.min_free_disk_mb * 1024 * 1024:
        log.error("disk almost full — rejecting capture from %s", device_id)
        return _error(503, "unavailable", "disk full", headers={"Retry-After": str(RETRY_AFTER_SEC)})

    received_at = utcnow()
    captured_at, clock_synced = _resolve_captured_at(h.get("x-captured-at"), received_at, device_id)
    event_id = make_event_id(device_id, captured_at)
    relpath = image_relpath(device_id, captured_at, event_id)
    image_file = settings.images_dir / relpath
    await asyncio.to_thread(save_atomic, image_file, body)

    now = to_iso(received_at)
    event = {
        "event_id": event_id, "device_id": device_id, "capture_id": capture_id, "status": db.RECEIVED,
        "captured_at": to_iso(captured_at), "received_at": now, "clock_synced": int(clock_synced),
        **_optional_headers(h, device_id),
        "image_path": relpath, "image_width": width, "image_height": height, "image_bytes": len(body),
        "updated_at": now,
    }
    with db.connect(db_path) as conn:
        try:
            store.insert_event(conn, event)
        except sqlite3.IntegrityError:
            # 같은 capture_id가 동시에 두 번 들어온 경우
            delete_image(image_file)
            existing = store.find_by_capture(conn, device_id, capture_id)
            if existing is None:
                raise
            return _duplicate(existing)

    request.app.state.worker.notify()
    log.info(
        "capture %s from %s (%dx%d, %d bytes, clock_synced=%s, trigger=%s)",
        event_id, device_id, width, height, len(body), clock_synced, event["trigger"],
    )
    return JSONResponse({"event_id": event_id, "status": db.RECEIVED}, status_code=202)


@router.get("/api/v1/events/{event_id}")
def get_event(event_id: str, request: Request):
    settings: Settings = request.app.state.settings
    with db.connect(db.db_path(settings.data_dir)) as conn:
        row = store.get_event(conn, event_id)
    if row is None:
        return _error(404, "not_found", f"no event {event_id}")
    return {
        "event_id": row["event_id"],
        "device_id": row["device_id"],
        "capture_id": row["capture_id"],
        "status": row["status"],
        "captured_at": row["captured_at"],
        "received_at": row["received_at"],
        "clock_synced": bool(row["clock_synced"]),
        "detected_at": row["detected_at"],
        "trigger": row["trigger"],
        "image": {
            "width": row["image_width"], "height": row["image_height"], "bytes": row["image_bytes"],
            "deleted": row["image_deleted_at"] is not None,
        },
        "infer_attempts": row["infer_attempts"],
        "last_error": row["last_error"],
        "uploaded_at": row["uploaded_at"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
    }


@router.get("/api/v1/stats")
def get_stats(request: Request, since: str | None = None, device_id: str | None = None):
    settings: Settings = request.app.state.settings
    if since:
        try:
            since = to_iso(parse_iso(since))
        except ValueError:
            return _error(400, "invalid_query", "since must be ISO 8601 with timezone, e.g. 2026-11-01T00:00:00Z")
    with db.connect(db.db_path(settings.data_dir)) as conn:
        return store.stats(conn, since, device_id)


@router.get("/healthz")
def healthz(request: Request):
    settings: Settings = request.app.state.settings
    with db.connect(db.db_path(settings.data_dir)) as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "inference_mode": settings.inference_mode}
