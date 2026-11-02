"""시각 처리. 모든 시각은 UTC이고, 'YYYY-MM-DDTHH:MM:SSZ' 문자열로 저장·전송한다 (docs/interfaces.md)."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(dt: datetime) -> str:
    """aware datetime → '2026-11-02T05:31:12Z'. 문자열 정렬 = 시간 정렬."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    """ISO 8601 → aware UTC datetime. 타임존 없는 값은 거부한다 (ValueError)."""
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        raise ValueError(f"timezone missing: {value!r}")
    return dt.astimezone(timezone.utc)
