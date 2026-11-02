"""events 테이블 읽기·쓰기 (cloud-sync 쪽). 연결은 호출자가 ppe_common.db.connect로 연다.

cloud-sync는 pending_upload만 건드린다. 갱신 쿼리는 모두 `status = pending_upload` 조건을 걸어
다른 상태의 이벤트를 덮어쓰지 않는다.
"""
import json
import sqlite3
from typing import Any

from ppe_common import db


def due_for_upload(conn: sqlite3.Connection, now: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE status = ? AND (next_sync_at IS NULL OR next_sync_at <= ?)"
        " ORDER BY received_at LIMIT ?",
        (db.PENDING_UPLOAD, now, limit),
    ).fetchall()


def pending_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM events WHERE status = ?", (db.PENDING_UPLOAD,)).fetchone()[0]


def mark_uploaded(conn: sqlite3.Connection, event_id: str, now: str) -> None:
    conn.execute(
        """UPDATE events SET status = ?, uploaded_at = ?, sync_attempts = sync_attempts + 1,
               next_sync_at = NULL, sync_error = NULL, updated_at = ?
           WHERE event_id = ? AND status = ?""",
        (db.UPLOADED, now, now, event_id, db.PENDING_UPLOAD),
    )


def schedule_sync_retry(conn: sqlite3.Connection, event_id: str, next_at: str, error: str, now: str) -> None:
    conn.execute(
        """UPDATE events SET sync_attempts = sync_attempts + 1, next_sync_at = ?, sync_error = ?, updated_at = ?
           WHERE event_id = ? AND status = ?""",
        (next_at, error[:500], now, event_id, db.PENDING_UPLOAD),
    )


def build_violation_row(row: sqlite3.Row) -> dict[str, Any]:
    """events 행 → Supabase `violations` upsert 본문 (docs/interfaces.md ③)."""
    result = json.loads(row["result_json"]) if row["result_json"] else {}
    return {
        "event_id": row["event_id"],
        "device_id": row["device_id"],
        "captured_at": row["captured_at"],
        "received_at": row["received_at"],
        "clock_synced": bool(row["clock_synced"]),
        "detected_at": row["detected_at"],
        "image_path": row["image_path"],
        "missing_helmet": bool(row["missing_helmet"]),
        "missing_vest": bool(row["missing_vest"]),
        "person_count": row["person_count"] or 0,
        "unknown_helmet_count": row["unknown_helmet_count"] or 0,
        "unknown_vest_count": row["unknown_vest_count"] or 0,
        "persons": result.get("persons", []),
        "model_version": row["model_version"],
        "inference_ms": row["inference_ms"],
    }
