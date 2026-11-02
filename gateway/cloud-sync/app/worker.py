"""pending_upload 이벤트를 폴링해서 업로드한다.

ingest와는 SQLite outbox(named volume)로만 연결된다. 성공하면 uploaded, 실패하면
next_sync_at까지 기다렸다가 다시 시도한다 (1→2→4…초, SYNC_MAX_BACKOFF_SEC 상한, 횟수 제한 없음).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from ppe_common import db
from ppe_common.timeutil import to_iso, utcnow

from . import store
from .config import Settings
from .uploader import Uploader, UploadError

log = logging.getLogger("cloud-sync.worker")


class SyncWorker:
    def __init__(self, settings: Settings, uploader: Uploader):
        self.settings = settings
        self.uploader = uploader
        self.db_path = db.db_path(settings.data_dir)
        self.last_upload_at: str | None = None

    async def run(self) -> None:
        log.info("sync worker started (mode=%s)", self.settings.sync_mode)
        while True:
            try:
                if await self.sync_due():
                    continue
            except Exception:
                log.exception("sync loop error")
            await asyncio.sleep(self.settings.sync_poll_interval_sec)

    async def sync_due(self, now: datetime | None = None) -> int:
        """지금 올릴 차례인 이벤트를 한 배치 처리하고 처리 건수를 돌려준다."""
        now_iso = to_iso(now or utcnow())
        with db.connect(self.db_path) as conn:
            rows = store.due_for_upload(conn, now_iso, self.settings.sync_batch_size)
        for row in rows:
            await self.sync_one(row)
        return len(rows)

    async def sync_one(self, row) -> bool:
        event_id = row["event_id"]
        path = self.settings.images_dir / row["image_path"]
        try:
            image = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            # 정상이라면 일어나지 않는다 (cleanup은 pending_upload 사진을 지우지 않음).
            # 사진 없이 행만 올리지 않도록 재시도로 남겨두고 사람이 확인한다.
            self._retry(row, "image_missing", level=logging.ERROR)
            return False

        try:
            await self.uploader.upload(row["image_path"], image, store.build_violation_row(row))
        except UploadError as e:
            self._retry(row, str(e))
            return False
        except Exception as e:  # 예상 못 한 오류도 사진을 잃지 않도록 재시도
            self._retry(row, f"{type(e).__name__}: {e}", level=logging.ERROR)
            return False

        now = to_iso(utcnow())
        with db.connect(self.db_path) as conn:
            store.mark_uploaded(conn, event_id, now)
        self.last_upload_at = now
        log.info("event %s → uploaded (%s, attempt %d)", event_id, row["image_path"], row["sync_attempts"] + 1)
        return True

    def backoff_sec(self, attempts: int) -> float:
        """이미 실패한 횟수(attempts) 기준 다음 대기 시간."""
        return min(self.settings.sync_max_backoff_sec, 2 ** min(attempts, 16))

    def _retry(self, row, error: str, level: int = logging.WARNING) -> None:
        delay = self.backoff_sec(row["sync_attempts"])
        now = utcnow()
        with db.connect(self.db_path) as conn:
            store.schedule_sync_retry(conn, row["event_id"], to_iso(now + timedelta(seconds=delay)), error, to_iso(now))
        log.log(level, "event %s upload failed (attempt %d), retry in %ss: %s",
                row["event_id"], row["sync_attempts"] + 1, delay, error)
