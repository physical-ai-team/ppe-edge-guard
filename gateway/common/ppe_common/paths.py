"""이미지 경로 규칙. 로컬 저장 경로(DATA_DIR/images/ 아래)와 Supabase Storage 경로를 같게 쓴다."""
import secrets
from datetime import datetime


def make_event_id(device_id: str, captured_at: datetime) -> str:
    """'{device_id}_{YYYYMMDDTHHMMSSZ}_{hex6}' (docs/interfaces.md 공통 규칙)."""
    return f"{device_id}_{captured_at:%Y%m%dT%H%M%SZ}_{secrets.token_hex(3)}"


def image_relpath(device_id: str, captured_at: datetime, event_id: str) -> str:
    """'{device_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg' — captured_at(UTC) 기준."""
    return f"{device_id}/{captured_at:%Y/%m/%d}/{event_id}.jpg"
