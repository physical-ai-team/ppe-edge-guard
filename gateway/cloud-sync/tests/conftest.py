import json
import itertools

import pytest

from app.config import Settings
from ppe_common import db
from ppe_common.timeutil import to_iso, utcnow

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
PERSONS = [
    {"box": [412, 180, 655, 940], "conf": 0.91, "helmet": "missing", "vest": "worn"},
    {"box": [820, 210, 1010, 900], "conf": 0.84, "helmet": "worn", "vest": "unknown"},
]
_seq = itertools.count()


@pytest.fixture
def make_settings(tmp_path):
    def _make(**kw) -> Settings:
        base = dict(data_dir=tmp_path, sync_mode="dry_run", sync_poll_interval_sec=0.05)
        base.update(kw)
        return Settings(**base)
    return _make


@pytest.fixture
def add_event(tmp_path):
    """ingest가 남기는 것과 같은 events 행 + 사진 파일을 만든다."""
    path = db.db_path(tmp_path)
    db.init_db(path)

    def _add(status: str = db.PENDING_UPLOAD, write_image: bool = True, **kw) -> str:
        n = next(_seq)
        event_id = kw.pop("event_id", f"cam-test_20261102T053112Z_{n:06x}")
        image_path = f"cam-test/2026/11/02/{event_id}.jpg"
        now = to_iso(utcnow())
        result = {"model_version": "mock-ppe-416-v1", "persons": PERSONS, "summary": {}}
        row = dict(
            event_id=event_id, device_id="cam-test", capture_id=f"cap-{n}", status=status,
            captured_at="2026-11-02T05:31:12Z", received_at=f"2026-11-02T05:31:{13 + n % 40:02d}Z",
            clock_synced=1, image_path=image_path, image_bytes=len(JPEG), detected_at="2026-11-02T05:31:14Z",
            result_json=json.dumps(result), model_version="mock-ppe-416-v1", inference_ms=142.7,
            person_count=2, missing_helmet=1, missing_vest=0, violation=1,
            unknown_helmet_count=0, unknown_vest_count=1, updated_at=now,
        )
        row.update(kw)
        cols = ", ".join(row)
        with db.connect(path) as conn:
            conn.execute(f"INSERT INTO events ({cols}) VALUES ({', '.join(':' + c for c in row)})", row)
        if write_image:
            f = tmp_path / "images" / image_path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(JPEG)
        return event_id

    return _add


@pytest.fixture
def get_event(tmp_path):
    def _get(event_id: str):
        with db.connect(db.db_path(tmp_path)) as conn:
            return dict(conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone())
    return _get
