"""SQLite outbox — ingest와 cloud-sync가 같은 named volume(DATA_DIR)에서 공유한다.

상태 전이 (docs/interfaces.md):
    received → inferring → compliant | pending_upload → uploaded
                         ↘ infer_failed (영구 오류: 손상 이미지, 파일 없음)
    일시 오류(inference 다운 등)는 received로 되돌리고 next_infer_at까지 대기한다.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

RECEIVED = "received"
INFERRING = "inferring"
COMPLIANT = "compliant"
PENDING_UPLOAD = "pending_upload"
UPLOADED = "uploaded"
INFER_FAILED = "infer_failed"

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id              TEXT PRIMARY KEY,
    device_id             TEXT NOT NULL,
    capture_id            TEXT NOT NULL,
    status                TEXT NOT NULL,
    captured_at           TEXT NOT NULL,
    received_at           TEXT NOT NULL,
    clock_synced          INTEGER NOT NULL,
    trigger               TEXT,
    detector_score        REAL,
    firmware_version      TEXT,

    image_path            TEXT NOT NULL,      -- DATA_DIR/images/ 기준 상대경로 = Storage 경로
    image_width           INTEGER,
    image_height          INTEGER,
    image_bytes           INTEGER NOT NULL,
    image_deleted_at      TEXT,

    infer_attempts        INTEGER NOT NULL DEFAULT 0,
    next_infer_at         TEXT,
    last_error            TEXT,

    detected_at           TEXT,
    result_json           TEXT,               -- inference 응답 전체
    model_version         TEXT,
    inference_ms          REAL,
    person_count          INTEGER,
    missing_helmet        INTEGER,
    missing_vest          INTEGER,
    violation             INTEGER,
    unknown_helmet_count  INTEGER,
    unknown_vest_count    INTEGER,

    -- cloud-sync 사용
    sync_attempts         INTEGER NOT NULL DEFAULT 0,
    next_sync_at          TEXT,
    sync_error            TEXT,
    uploaded_at           TEXT,

    updated_at            TEXT NOT NULL,
    UNIQUE (device_id, capture_id)
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events (status, next_infer_at);
CREATE INDEX IF NOT EXISTS idx_events_received_at ON events (received_at);
"""


def db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "gateway.db"


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """짧게 쓰고 닫는 연결. autocommit 모드 — 여러 문장을 묶을 땐 `with conn:` 대신 BEGIN IMMEDIATE 사용."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
