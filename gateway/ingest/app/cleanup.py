"""로컬 사진 정리 (CLAUDE.md "로컬 사진 정책").

1) 보관 기간: VIOLATION_RETENTION_DAYS가 지난 사진 삭제
   - uploaded: uploaded_at 기준
   - compliant(디버그 보관분) / infer_failed: received_at 기준
2) 용량 상한: LOCAL_IMAGE_MAX_MB 초과 시 오래된 것부터 삭제
   1순위 compliant·infer_failed → 2순위 uploaded
   received / inferring / pending_upload 사진은 절대 삭제하지 않는다 (경고 로그만).

DB 기록(통계)은 지우지 않고 image_deleted_at만 남긴다.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ppe_common import db
from ppe_common.timeutil import to_iso, utcnow

from . import store
from .config import Settings
from .images import delete_image

log = logging.getLogger("ingest.cleanup")

_HAS_IMAGE = "image_deleted_at IS NULL"
_DISPOSABLE = (db.COMPLIANT, db.INFER_FAILED)


def _delete(conn: sqlite3.Connection, images_dir: Path, row, now: str) -> int:
    delete_image(images_dir / row["image_path"])
    store.mark_image_deleted(conn, row["event_id"], now)
    return row["image_bytes"]


def stored_bytes(conn: sqlite3.Connection) -> int:
    return conn.execute(f"SELECT COALESCE(SUM(image_bytes), 0) FROM events WHERE {_HAS_IMAGE}").fetchone()[0]


def run_cleanup(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> dict:
    now = now or utcnow()
    now_iso = to_iso(now)
    cutoff = to_iso(now - timedelta(days=settings.violation_retention_days))
    images_dir = settings.images_dir
    expired = conn.execute(
        f"""SELECT event_id, image_path, image_bytes FROM events
            WHERE {_HAS_IMAGE} AND (
                (status = ? AND uploaded_at < ?) OR (status IN (?, ?) AND received_at < ?))""",
        (db.UPLOADED, cutoff, *_DISPOSABLE, cutoff),
    ).fetchall()
    for row in expired:
        _delete(conn, images_dir, row, now_iso)

    total = stored_bytes(conn)
    limit = settings.local_image_max_bytes
    over_cap_deleted = 0
    if total > limit:
        candidates = conn.execute(
            f"""SELECT event_id, image_path, image_bytes FROM events
                WHERE {_HAS_IMAGE} AND status IN (?, ?) ORDER BY received_at""",
            _DISPOSABLE,
        ).fetchall() + conn.execute(
            f"SELECT event_id, image_path, image_bytes FROM events WHERE {_HAS_IMAGE} AND status = ? ORDER BY uploaded_at",
            (db.UPLOADED,),
        ).fetchall()
        for row in candidates:
            if total <= limit:
                break
            total -= _delete(conn, images_dir, row, now_iso)
            over_cap_deleted += 1
        if total > limit:
            log.warning(
                "image storage %.1f MB exceeds LOCAL_IMAGE_MAX_MB=%d, but remaining images are not yet "
                "uploaded/decided — keeping them", total / 1024 / 1024, settings.local_image_max_mb,
            )

    if expired or over_cap_deleted:
        log.info("cleanup: %d expired, %d over-cap images deleted", len(expired), over_cap_deleted)
    return {"expired": len(expired), "over_cap": over_cap_deleted, "stored_bytes": total}


def remove_stale_tmp(images_dir: Path) -> None:
    """저장 도중 죽어서 남은 *.tmp 파일 제거 (시작 시 1회)."""
    for tmp in images_dir.rglob("*.jpg.tmp"):
        tmp.unlink(missing_ok=True)


async def cleanup_loop(settings: Settings) -> None:
    path = db.db_path(settings.data_dir)

    def _once() -> None:
        with db.connect(path) as conn:
            run_cleanup(conn, settings)

    while True:
        try:
            await asyncio.to_thread(_once)
        except Exception:
            log.exception("cleanup failed")
        await asyncio.sleep(settings.cleanup_interval_sec)
