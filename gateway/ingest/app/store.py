"""events 테이블 읽기·쓰기 (ingest 쪽). 연결은 호출자가 ppe_common.db.connect로 연다."""
import json
import sqlite3
from typing import Any

from ppe_common import db

_INSERT_COLUMNS = (
    "event_id", "device_id", "capture_id", "status", "captured_at", "received_at",
    "clock_synced", "trigger", "detector_score", "firmware_version",
    "image_path", "image_width", "image_height", "image_bytes", "updated_at",
)


def insert_event(conn: sqlite3.Connection, ev: dict[str, Any]) -> None:
    """(device_id, capture_id) 중복이면 sqlite3.IntegrityError."""
    cols = ", ".join(_INSERT_COLUMNS)
    marks = ", ".join(f":{c}" for c in _INSERT_COLUMNS)
    conn.execute(f"INSERT INTO events ({cols}) VALUES ({marks})", ev)


def get_event(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()


def find_by_capture(conn: sqlite3.Connection, device_id: str, capture_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM events WHERE device_id = ? AND capture_id = ?", (device_id, capture_id)
    ).fetchone()


def reset_inferring(conn: sqlite3.Connection, now: str) -> int:
    """재시작 시 처리 중이던 이벤트를 received로 되돌린다."""
    cur = conn.execute(
        "UPDATE events SET status = ?, next_infer_at = NULL, updated_at = ? WHERE status = ?",
        (db.RECEIVED, now, db.INFERRING),
    )
    return cur.rowcount


def claim_next_for_inference(conn: sqlite3.Connection, now: str) -> sqlite3.Row | None:
    """대기 중인 가장 오래된 이벤트를 inferring으로 바꾸고 돌려준다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT event_id FROM events WHERE status = ? AND (next_infer_at IS NULL OR next_infer_at <= ?)"
            " ORDER BY received_at LIMIT 1",
            (db.RECEIVED, now),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE events SET status = ?, infer_attempts = infer_attempts + 1, updated_at = ?"
            " WHERE event_id = ?",
            (db.INFERRING, now, row["event_id"]),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return get_event(conn, row["event_id"])


def next_infer_due(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MIN(COALESCE(next_infer_at, '')) AS due FROM events WHERE status = ?", (db.RECEIVED,)
    ).fetchone()
    return row["due"]


def save_result(conn: sqlite3.Connection, event_id: str, status: str, result: dict, detected_at: str) -> None:
    s = result["summary"]
    conn.execute(
        """UPDATE events SET status = ?, detected_at = ?, result_json = ?, model_version = ?,
               inference_ms = ?, person_count = ?, missing_helmet = ?, missing_vest = ?, violation = ?,
               unknown_helmet_count = ?, unknown_vest_count = ?, next_infer_at = NULL, last_error = NULL,
               updated_at = ?
           WHERE event_id = ?""",
        (
            status, detected_at, json.dumps(result, ensure_ascii=False), result.get("model_version"),
            result.get("inference_ms"), s["person_count"], int(s["missing_helmet"]), int(s["missing_vest"]),
            int(s["violation"]), s.get("unknown_helmet_count", 0), s.get("unknown_vest_count", 0),
            detected_at, event_id,
        ),
    )


def schedule_infer_retry(conn: sqlite3.Connection, event_id: str, next_at: str, error: str, now: str) -> None:
    conn.execute(
        "UPDATE events SET status = ?, next_infer_at = ?, last_error = ?, updated_at = ? WHERE event_id = ?",
        (db.RECEIVED, next_at, error[:500], now, event_id),
    )


def mark_infer_failed(conn: sqlite3.Connection, event_id: str, error: str, now: str) -> None:
    conn.execute(
        "UPDATE events SET status = ?, last_error = ?, next_infer_at = NULL, updated_at = ? WHERE event_id = ?",
        (db.INFER_FAILED, error[:500], now, event_id),
    )


def mark_image_deleted(conn: sqlite3.Connection, event_id: str, now: str) -> None:
    conn.execute(
        "UPDATE events SET image_deleted_at = ?, updated_at = ? WHERE event_id = ?", (now, now, event_id)
    )


def stats(conn: sqlite3.Connection, since: str | None, device_id: str | None) -> dict[str, Any]:
    where, params = [], []
    if since:
        where.append("received_at >= ?")
        params.append(since)
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    agg = conn.execute(
        f"""SELECT COUNT(*) AS events,
                   COALESCE(SUM(person_count), 0) AS persons,
                   COALESCE(SUM(violation), 0) AS violations,
                   COALESCE(SUM(unknown_helmet_count), 0) AS unknown_helmet_count,
                   COALESCE(SUM(unknown_vest_count), 0) AS unknown_vest_count
            FROM events {clause}""",
        params,
    ).fetchone()
    by_status = {
        r["status"]: r["n"]
        for r in conn.execute(f"SELECT status, COUNT(*) AS n FROM events {clause} GROUP BY status", params)
    }
    model_clause = f"{clause} {'AND' if clause else 'WHERE'} model_version IS NOT NULL"
    by_model = {
        r["model_version"]: r["n"]
        for r in conn.execute(
            f"SELECT model_version, COUNT(*) AS n FROM events {model_clause} GROUP BY model_version", params
        )
    }
    persons = agg["persons"]
    return {
        "since": since,
        "device_id": device_id,
        "events": agg["events"],
        "by_status": by_status,
        "persons": persons,
        "violations": agg["violations"],
        "unknown_helmet_count": agg["unknown_helmet_count"],
        "unknown_vest_count": agg["unknown_vest_count"],
        "unknown_helmet_rate": round(agg["unknown_helmet_count"] / persons, 3) if persons else 0,
        "unknown_vest_rate": round(agg["unknown_vest_count"] / persons, 3) if persons else 0,
        "by_model_version": by_model,
    }
