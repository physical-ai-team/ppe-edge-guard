"""pending_upload → uploaded 전이, 업로드 형식(③ 계약), 실패 시 백오프 재시도."""
import asyncio
import json
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.uploader import DryRunUploader, SupabaseUploader
from app.worker import SyncWorker
from conftest import JPEG, PERSONS
from ppe_common import db
from ppe_common.timeutil import parse_iso, utcnow

# docs/interfaces.md ③ "cloud-sync가 보내는 upsert 예시"의 키
CONTRACT_KEYS = {
    "event_id", "device_id", "captured_at", "received_at", "clock_synced", "detected_at", "image_path",
    "missing_helmet", "missing_vest", "person_count", "unknown_helmet_count", "unknown_vest_count",
    "persons", "model_version", "inference_ms",
}


def _dry_worker(settings: Settings) -> SyncWorker:
    return SyncWorker(settings, DryRunUploader(settings.dry_run_dir))


def test_dry_run_uploads_and_marks_uploaded(make_settings, add_event, get_event, tmp_path):
    settings = make_settings()
    event_id = add_event()
    assert asyncio.run(_dry_worker(settings).sync_due()) == 1

    ev = get_event(event_id)
    assert ev["status"] == db.UPLOADED
    assert ev["uploaded_at"] and ev["sync_attempts"] == 1 and ev["sync_error"] is None

    out = tmp_path / "sync-dryrun" / "cam-test/2026/11/02" / f"{event_id}.jpg"
    assert out.read_bytes() == JPEG
    row = json.loads(out.with_name(out.name + ".json").read_text(encoding="utf-8"))
    assert set(row) == CONTRACT_KEYS
    assert row == {
        "event_id": event_id,
        "device_id": "cam-test",
        "captured_at": "2026-11-02T05:31:12Z",
        "received_at": ev["received_at"],
        "clock_synced": True,
        "detected_at": "2026-11-02T05:31:14Z",
        "image_path": f"cam-test/2026/11/02/{event_id}.jpg",
        "missing_helmet": True,
        "missing_vest": False,
        "person_count": 2,
        "unknown_helmet_count": 0,
        "unknown_vest_count": 1,
        "persons": PERSONS,
        "model_version": "mock-ppe-416-v1",
        "inference_ms": 142.7,
    }
    # 로컬 사진은 보관 기간 동안 남긴다 (삭제는 ingest cleanup 담당)
    assert (tmp_path / "images" / ev["image_path"]).exists()


def test_only_pending_upload_is_synced(make_settings, add_event, get_event):
    settings = make_settings()
    others = [add_event(status=s) for s in (db.RECEIVED, db.INFERRING, db.COMPLIANT, db.INFER_FAILED, db.UPLOADED)]
    pending = add_event()
    assert asyncio.run(_dry_worker(settings).sync_due()) == 1
    assert get_event(pending)["status"] == db.UPLOADED
    assert [get_event(e)["sync_attempts"] for e in others] == [0] * len(others)


def test_dry_run_failure_backs_off_then_recovers(make_settings, add_event, get_event, tmp_path):
    settings = make_settings()
    tmp_path.joinpath("sync-dryrun").write_text("not a dir")  # 디렉터리를 못 만들게 해서 업로드 실패 흉내
    event_id = add_event()
    worker = _dry_worker(settings)

    asyncio.run(worker.sync_due())
    ev = get_event(event_id)
    assert ev["status"] == db.PENDING_UPLOAD
    assert ev["sync_attempts"] == 1
    assert ev["sync_error"].startswith("dry_run:")
    next_at = parse_iso(ev["next_sync_at"])
    assert next_at > utcnow() - timedelta(seconds=1)

    # 대기 시간 전에는 다시 시도하지 않는다
    assert asyncio.run(worker.sync_due(now=next_at - timedelta(seconds=1))) == 0

    tmp_path.joinpath("sync-dryrun").unlink()  # "네트워크 복구"
    assert asyncio.run(worker.sync_due(now=next_at)) == 1
    ev = get_event(event_id)
    assert ev["status"] == db.UPLOADED
    assert ev["sync_attempts"] == 2 and ev["sync_error"] is None and ev["next_sync_at"] is None


def test_missing_image_is_not_uploaded_without_photo(make_settings, add_event, get_event, tmp_path):
    settings = make_settings()
    event_id = add_event(write_image=False)
    asyncio.run(_dry_worker(settings).sync_due())
    ev = get_event(event_id)
    assert ev["status"] == db.PENDING_UPLOAD
    assert ev["sync_error"] == "image_missing"
    assert not (tmp_path / "sync-dryrun").exists()


def test_backoff_is_exponential_and_capped(make_settings):
    worker = _dry_worker(make_settings(sync_max_backoff_sec=300))
    assert [worker.backoff_sec(n) for n in (0, 1, 2, 3, 8, 9, 50)] == [1, 2, 4, 8, 256, 300, 300]


def test_settings_require_supabase_credentials(tmp_path):
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings(data_dir=tmp_path, sync_mode="supabase", supabase_url="", supabase_service_role_key="k")
    with pytest.raises(ValueError, match="SERVICE_ROLE_KEY"):
        Settings(data_dir=tmp_path, sync_mode="supabase", supabase_url="https://x.supabase.co",
                 supabase_service_role_key=" ")
    Settings(data_dir=tmp_path, sync_mode="dry_run")  # dry_run은 키 없이 동작


# ---------- SYNC_MODE=supabase (HTTP는 MockTransport로 대체) ----------

def _supabase_worker(settings, handler) -> SyncWorker:
    up = SupabaseUploader("https://proj.supabase.co/", "service-key", "violation-images", 5,
                          transport=httpx.MockTransport(handler))
    return SyncWorker(settings, up)


def test_supabase_requests_follow_contract(make_settings, add_event, get_event):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200 if "storage" in request.url.path else 201)

    event_id = add_event()
    asyncio.run(_supabase_worker(make_settings(), handler).sync_due())
    assert get_event(event_id)["status"] == db.UPLOADED

    storage, table = seen
    # 1) Storage: 결정적 경로에 upsert
    assert storage.method == "POST"
    assert storage.url.path == f"/storage/v1/object/violation-images/cam-test/2026/11/02/{event_id}.jpg"
    assert storage.headers["content-type"] == "image/jpeg"
    assert storage.headers["x-upsert"] == "true"
    assert storage.content == JPEG
    # 2) 테이블: event_id 기준 upsert
    assert table.method == "POST"
    assert table.url.path == "/rest/v1/violations"
    assert table.url.params["on_conflict"] == "event_id"
    assert "resolution=merge-duplicates" in table.headers["prefer"]
    body = json.loads(table.content)
    assert set(body) == CONTRACT_KEYS and body["event_id"] == event_id
    for r in seen:
        assert r.headers["apikey"] == "service-key"
        assert r.headers["authorization"] == "Bearer service-key"


def test_supabase_storage_failure_skips_table(make_settings, add_event, get_event):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.path)
        return httpx.Response(503, text="unavailable")

    event_id = add_event()
    asyncio.run(_supabase_worker(make_settings(), handler).sync_due())
    ev = get_event(event_id)
    assert ev["status"] == db.PENDING_UPLOAD
    assert ev["sync_error"].startswith("storage: 503")
    assert len(seen) == 1  # 사진이 안 올라가면 행도 올리지 않는다


@pytest.mark.parametrize("fail", ["table_4xx", "network"])
def test_supabase_table_failure_retries_whole_upload(make_settings, add_event, get_event, fail):
    calls = {"storage": 0, "table": 0}

    def handler(request: httpx.Request):
        step = "storage" if "storage" in request.url.path else "table"
        calls[step] += 1
        if step == "table" and calls["table"] == 1:
            if fail == "network":
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(404, json={"message": "relation \"violations\" does not exist"})
        return httpx.Response(200)

    event_id = add_event()
    worker = _supabase_worker(make_settings(), handler)
    asyncio.run(worker.sync_due())
    ev = get_event(event_id)
    assert ev["status"] == db.PENDING_UPLOAD and ev["sync_error"].startswith("table:")

    asyncio.run(worker.sync_due(now=parse_iso(ev["next_sync_at"])))
    assert get_event(event_id)["status"] == db.UPLOADED
    assert calls == {"storage": 2, "table": 2}  # 사진 재업로드는 upsert라 멱등


# ---------- v1.2: 영구 오류 → upload_failed ----------

def _run_until_settled(worker, get_event, event_id, rounds):
    """next_sync_at을 기다리지 않고 바로 다음 시도를 돌린다."""
    for _ in range(rounds):
        ev = get_event(event_id)
        if ev["status"] != db.PENDING_UPLOAD:
            break
        now = parse_iso(ev["next_sync_at"]) if ev["next_sync_at"] else None
        asyncio.run(worker.sync_due(now=now))
    return get_event(event_id)


@pytest.mark.parametrize("code,permanent", [
    (400, True), (401, True), (403, True), (404, True), (409, True), (422, True),
    (408, False), (429, False), (500, False), (502, False), (503, False),
])
def test_status_classification(make_settings, add_event, get_event, code, permanent):
    event_id = add_event()
    worker = _supabase_worker(make_settings(), lambda r: httpx.Response(code, text="x"))
    asyncio.run(worker.sync_due())
    ev = get_event(event_id)
    assert ev["status"] == db.PENDING_UPLOAD
    assert ev["sync_permanent_failures"] == int(permanent)


def test_permanent_errors_mark_upload_failed_after_limit(make_settings, add_event, get_event, tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"message": "Invalid API key"})

    event_id = add_event()
    worker = _supabase_worker(make_settings(sync_max_permanent_failures=3), handler)
    ev = _run_until_settled(worker, get_event, event_id, rounds=10)
    assert ev["status"] == db.UPLOAD_FAILED
    assert ev["sync_attempts"] == 3 and ev["sync_permanent_failures"] == 3
    assert ev["sync_error"].startswith("storage: 401") and ev["next_sync_at"] is None
    assert len(calls) == 3
    # 재시도 중단: 더 이상 가져가지 않는다
    assert asyncio.run(worker.sync_due(now=utcnow() + timedelta(days=1))) == 0
    # 사진은 로컬에 남는다
    assert (tmp_path / "images" / ev["image_path"]).exists()


def test_missing_image_marks_upload_failed_after_limit(make_settings, add_event, get_event):
    event_id = add_event(write_image=False)
    worker = _dry_worker(make_settings())  # 기본 5회
    ev = _run_until_settled(worker, get_event, event_id, rounds=10)
    assert ev["status"] == db.UPLOAD_FAILED
    assert ev["sync_permanent_failures"] == 5 and ev["sync_error"] == "image_missing"


def test_transient_errors_retry_forever(make_settings, add_event, get_event):
    event_id = add_event()
    worker = _supabase_worker(make_settings(sync_max_permanent_failures=2),
                              lambda r: httpx.Response(503, text="down"))
    ev = _run_until_settled(worker, get_event, event_id, rounds=20)
    assert ev["status"] == db.PENDING_UPLOAD
    assert ev["sync_attempts"] == 20 and ev["sync_permanent_failures"] == 0


def test_only_permanent_failures_count_toward_limit(make_settings, add_event, get_event):
    codes = iter([503, 503, 503, 404, 429, 404])  # 영구 2회, 일시 4회

    def handler(request):
        return httpx.Response(next(codes, 200))

    event_id = add_event()
    worker = _supabase_worker(make_settings(sync_max_permanent_failures=3), handler)
    ev = _run_until_settled(worker, get_event, event_id, rounds=10)
    assert ev["status"] == db.UPLOADED


def test_requeue_upload_failed(make_settings, add_event, get_event, tmp_path, monkeypatch, capsys):
    from app import requeue

    failed = [add_event(status=db.UPLOAD_FAILED, sync_permanent_failures=5, sync_attempts=5) for _ in range(2)]
    other = add_event(status=db.UPLOADED)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    requeue.main([failed[0]])
    assert get_event(failed[0])["status"] == db.PENDING_UPLOAD
    assert get_event(failed[0])["sync_permanent_failures"] == 0
    assert get_event(failed[1])["status"] == db.UPLOAD_FAILED

    requeue.main([])
    assert "requeued 1" in capsys.readouterr().out.splitlines()[-1]
    assert get_event(failed[1])["status"] == db.PENDING_UPLOAD
    assert get_event(other)["status"] == db.UPLOADED

    asyncio.run(_dry_worker(make_settings()).sync_due())
    assert all(get_event(e)["status"] == db.UPLOADED for e in failed)


# ---------- 서비스 ----------

def test_healthz_and_background_worker(make_settings, add_event, get_event):
    event_id = add_event()
    with TestClient(create_app(make_settings())) as client:
        for _ in range(100):
            if get_event(event_id)["status"] == db.UPLOADED:
                break
            time.sleep(0.05)
        body = client.get("/healthz").json()
    assert get_event(event_id)["status"] == db.UPLOADED
    assert body["status"] == "ok" and body["sync_mode"] == "dry_run"
    assert body["pending_upload"] == 0 and body["last_upload_at"]
