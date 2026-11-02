"""로컬 사진 보관 기간 · 용량 상한 정책."""
from datetime import datetime, timedelta, timezone

from ppe_common import db
from ppe_common.timeutil import to_iso

from app import store
from app.cleanup import run_cleanup

NOW = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
MB = 1024 * 1024


def _add(conn, settings, event_id, status, age_days, size=MB, uploaded_age_days=None):
    received = to_iso(NOW - timedelta(days=age_days))
    rel = f"cam-test/{event_id}.jpg"
    path = settings.images_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8" + b"\0" * 10)
    store.insert_event(conn, {
        "event_id": event_id, "device_id": "cam-test", "capture_id": event_id, "status": status,
        "captured_at": received, "received_at": received, "clock_synced": 1, "trigger": None,
        "detector_score": None, "firmware_version": None, "image_path": rel, "image_width": 1,
        "image_height": 1, "image_bytes": size, "updated_at": received,
    })
    if uploaded_age_days is not None:
        conn.execute("UPDATE events SET uploaded_at = ? WHERE event_id = ?",
                     (to_iso(NOW - timedelta(days=uploaded_age_days)), event_id))
    return path


def _setup(make_settings, **kw):
    settings = make_settings(**kw)
    db.init_db(db.db_path(settings.data_dir))
    return settings


def test_retention_deletes_old_uploaded_and_debug_compliant(make_settings):
    settings = _setup(make_settings, violation_retention_days=7)
    with db.connect(db.db_path(settings.data_dir)) as conn:
        old_up = _add(conn, settings, "old-up", db.UPLOADED, 10, uploaded_age_days=8)
        new_up = _add(conn, settings, "new-up", db.UPLOADED, 10, uploaded_age_days=2)  # 업로드 기준으로 판단
        old_ok = _add(conn, settings, "old-ok", db.COMPLIANT, 8)
        old_pending = _add(conn, settings, "old-pending", db.PENDING_UPLOAD, 30)
        result = run_cleanup(conn, settings, now=NOW)
        assert result["expired"] == 2
        assert not old_up.exists() and not old_ok.exists()
        assert new_up.exists() and old_pending.exists()
        assert store.get_event(conn, "old-up")["image_deleted_at"] is not None
        assert store.get_event(conn, "old-up")["status"] == db.UPLOADED  # 기록은 남는다


def test_cap_deletes_disposable_first_then_uploaded_never_pending(make_settings):
    settings = _setup(make_settings, local_image_max_mb=3, violation_retention_days=30)
    with db.connect(db.db_path(settings.data_dir)) as conn:
        uploaded = _add(conn, settings, "uploaded", db.UPLOADED, 5, uploaded_age_days=5)
        compliant = _add(conn, settings, "compliant", db.COMPLIANT, 1)
        failed = _add(conn, settings, "failed", db.INFER_FAILED, 2)
        pending = [_add(conn, settings, f"pending-{i}", db.PENDING_UPLOAD, 3) for i in range(2)]
        received = _add(conn, settings, "received", db.RECEIVED, 0)
        # 총 7MB, 상한 3MB → 4개 삭제 필요, 삭제 가능한 건 3개뿐
        result = run_cleanup(conn, settings, now=NOW)
        assert result["over_cap"] == 3
        assert not uploaded.exists() and not compliant.exists() and not failed.exists()
        assert all(p.exists() for p in pending) and received.exists()
        assert result["stored_bytes"] == 3 * MB


def test_upload_failed_never_deleted_and_counted(make_settings):
    settings = _setup(make_settings, local_image_max_mb=1, violation_retention_days=7)
    with db.connect(db.db_path(settings.data_dir)) as conn:
        failed = [_add(conn, settings, f"upfail-{i}", db.UPLOAD_FAILED, 30, uploaded_age_days=None) for i in range(2)]
        result = run_cleanup(conn, settings, now=NOW)
        assert result["expired"] == 0 and result["over_cap"] == 0
        assert all(p.exists() for p in failed)
        assert result["upload_failed"] == 2
        assert result["stored_bytes"] == 2 * MB  # 상한(1MB)을 넘어도 지우지 않는다


def test_init_db_migrates_v1_schema(tmp_path):
    path = db.db_path(tmp_path)
    with db.connect(path) as conn:  # v1 스키마 (sync_permanent_failures 없음)
        conn.executescript(db._SCHEMA.replace(
            "sync_permanent_failures INTEGER NOT NULL DEFAULT 0,   -- v2: 영구 오류(4xx, 사진 없음) 횟수\n", ""))
        conn.execute("PRAGMA user_version=1")
        assert "sync_permanent_failures" not in {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    db.init_db(path)
    db.init_db(path)  # 두 번 불러도 안전 (ingest·cloud-sync 동시 시작)
    with db.connect(path) as conn:
        assert "sync_permanent_failures" in {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_cap_stops_once_under_limit(make_settings):
    settings = _setup(make_settings, local_image_max_mb=2, violation_retention_days=30)
    with db.connect(db.db_path(settings.data_dir)) as conn:
        older = _add(conn, settings, "older", db.COMPLIANT, 3)
        newer = _add(conn, settings, "newer", db.COMPLIANT, 1)
        up = _add(conn, settings, "up", db.UPLOADED, 1, uploaded_age_days=1)
        assert run_cleanup(conn, settings, now=NOW)["over_cap"] == 1
        assert not older.exists()
        assert newer.exists() and up.exists()
