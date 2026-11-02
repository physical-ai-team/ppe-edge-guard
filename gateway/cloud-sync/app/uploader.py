"""위반 이벤트 업로드 (docs/interfaces.md ③).

SYNC_MODE=supabase : Storage 업로드(upsert) → violations 테이블 upsert(on_conflict=event_id)
SYNC_MODE=dry_run  : Supabase 대신 DATA_DIR/sync-dryrun/ 아래에 같은 경로로 사진과 JSON을 기록

두 단계 모두 멱등이다. 중간에 실패하면 처음부터 다시 해도 결과가 같다.
순서는 항상 사진 → 행이다 (웹이 사진 없는 행을 보지 않도록).

오류 분류 (docs/interfaces.md v1.2):
  일시 오류 — 연결 실패, 타임아웃, 5xx, 408, 429, dry_run 쓰기 실패 → 무한 재시도
  영구 오류 — 그 밖의 4xx (잘못된 키·버킷·테이블·본문) → SYNC_MAX_PERMANENT_FAILURES회 후 upload_failed
"""
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .config import Settings

TABLE = "violations"


_TRANSIENT_4XX = (408, 429)


class UploadError(Exception):
    """업로드 실패. permanent=False면 무한 재시도, True면 횟수 제한 후 upload_failed."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


def is_permanent_status(status_code: int) -> bool:
    return 400 <= status_code < 500 and status_code not in _TRANSIENT_4XX


class Uploader(Protocol):
    async def upload(self, image_path: str, image: bytes, row: dict[str, Any]) -> None: ...
    async def aclose(self) -> None: ...


class SupabaseUploader:
    def __init__(self, url: str, service_role_key: str, bucket: str, timeout: float,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.bucket = bucket
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"},
        )

    async def upload(self, image_path: str, image: bytes, row: dict[str, Any]) -> None:
        await self._request(
            "storage",
            "POST",
            f"/storage/v1/object/{quote(self.bucket)}/{quote(image_path)}",
            content=image,
            headers={"Content-Type": "image/jpeg", "x-upsert": "true"},
        )
        await self._request(
            "table",
            "POST",
            f"/rest/v1/{TABLE}",
            params={"on_conflict": "event_id"},
            json=row,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    async def _request(self, step: str, method: str, url: str, **kw) -> None:
        try:
            r = await self._client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise UploadError(f"{step}: {type(e).__name__}: {e}") from e
        if r.status_code >= 300:
            raise UploadError(f"{step}: {r.status_code} {r.text[:200]}", permanent=is_permanent_status(r.status_code))

    async def aclose(self) -> None:
        await self._client.aclose()


class DryRunUploader:
    """Supabase 경로 구조를 그대로 흉내 낸다: {dir}/{image_path}, {dir}/{image_path}.json"""

    def __init__(self, root: Path):
        self.root = Path(root)

    async def upload(self, image_path: str, image: bytes, row: dict[str, Any]) -> None:
        target = self.root / image_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, image)
            _atomic_write(target.with_name(target.name + ".json"),
                          json.dumps(row, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError as e:
            raise UploadError(f"dry_run: {type(e).__name__}: {e}") from e

    async def aclose(self) -> None:
        pass


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def build_uploader(settings: Settings) -> Uploader:
    if settings.sync_mode == "dry_run":
        return DryRunUploader(settings.dry_run_dir)
    return SupabaseUploader(
        settings.supabase_url, settings.supabase_service_role_key, settings.supabase_bucket, settings.sync_timeout_sec
    )
