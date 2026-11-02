"""received 이벤트를 하나씩 꺼내 inference에 보내고 결과에 따라 상태를 바꾼다.

Pi CPU 하나를 inference가 쓰므로 순차 처리한다. 새 사진이 오면 notify()로 즉시 깨운다.
"""
import asyncio
import logging
from datetime import timedelta

from ppe_common import db
from ppe_common.timeutil import parse_iso, to_iso, utcnow

from . import store
from .config import Settings
from .images import delete_image
from .inference_client import InferenceClient, PermanentInferenceError

log = logging.getLogger("ingest.worker")

IDLE_POLL_SEC = 5.0


class InferenceWorker:
    def __init__(self, settings: Settings, client: InferenceClient):
        self.settings = settings
        self.client = client
        self.db_path = db.db_path(settings.data_dir)
        self._wakeup = asyncio.Event()

    def notify(self) -> None:
        self._wakeup.set()

    async def run(self) -> None:
        log.info("inference worker started (mode=%s)", self.settings.inference_mode)
        while True:
            self._wakeup.clear()
            try:
                if await self.process_one():
                    continue
            except Exception:
                log.exception("worker loop error")
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self._idle_timeout())
            except asyncio.TimeoutError:
                pass

    def _idle_timeout(self) -> float:
        with db.connect(self.db_path) as conn:
            due = store.next_infer_due(conn)
        if due is None:
            return IDLE_POLL_SEC
        if due == "":
            return 0.05
        wait = (parse_iso(due) - utcnow()).total_seconds()
        return min(max(wait, 0.05), IDLE_POLL_SEC)

    async def process_one(self) -> bool:
        """이벤트 하나를 처리했으면 True, 대기 중인 이벤트가 없으면 False."""
        now = to_iso(utcnow())
        with db.connect(self.db_path) as conn:
            row = store.claim_next_for_inference(conn, now)
        if row is None:
            return False

        event_id = row["event_id"]
        path = self.settings.images_dir / row["image_path"]
        try:
            image = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            self._fail(event_id, "image_missing")
            return True

        try:
            result = await self.client.infer(image, event_id)
            self._apply_result(row, result)
        except PermanentInferenceError as e:
            self._fail(event_id, str(e))
        except Exception as e:  # 일시 오류: inference 다운, 타임아웃, 잘못된 응답, DB 잠금 등
            self._retry(event_id, row["infer_attempts"], f"{type(e).__name__}: {e}")
        return True

    def _apply_result(self, row, result: dict) -> None:
        event_id = row["event_id"]
        summary = result["summary"]
        violation = bool(summary["violation"])
        status = db.PENDING_UPLOAD if violation else db.COMPLIANT
        detected_at = to_iso(utcnow())
        with db.connect(self.db_path) as conn:
            store.save_result(conn, event_id, status, result, detected_at)
            # 상태를 먼저 저장한 뒤 삭제 — 중간에 죽어도 cleanup이 남은 파일을 정리한다
            if not violation and not self.settings.debug_keep_compliant:
                delete_image(self.settings.images_dir / row["image_path"])
                store.mark_image_deleted(conn, event_id, detected_at)
        log.info(
            "event %s → %s (persons=%s helmet_missing=%s vest_missing=%s model=%s)",
            event_id, status, summary["person_count"], summary["missing_helmet"],
            summary["missing_vest"], result.get("model_version"),
        )

    def _retry(self, event_id: str, attempts: int, error: str) -> None:
        delay = min(self.settings.infer_max_backoff_sec, 2 ** min(attempts - 1, 16))
        now = utcnow()
        with db.connect(self.db_path) as conn:
            store.schedule_infer_retry(conn, event_id, to_iso(now + timedelta(seconds=delay)), error, to_iso(now))
        log.warning("event %s inference failed (attempt %d), retry in %ss: %s", event_id, attempts, delay, error)

    def _fail(self, event_id: str, error: str) -> None:
        with db.connect(self.db_path) as conn:
            store.mark_infer_failed(conn, event_id, error, to_iso(utcnow()))
        log.error("event %s infer_failed: %s", event_id, error)
