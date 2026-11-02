"""cloud-sync 서비스 진입점. 실행: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8002

HTTP는 /healthz만 연다. 실제 일은 백그라운드 SyncWorker가 한다.
"""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from ppe_common import db
from ppe_common.logs import setup_logging

from . import store
from .config import Settings
from .uploader import Uploader, build_uploader
from .worker import SyncWorker

log = logging.getLogger("cloud-sync")


def create_app(settings: Settings | None = None, uploader: Uploader | None = None,
               start_worker: bool = True) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        db.init_db(db.db_path(settings.data_dir))  # ingest보다 먼저 떠도 되도록 (IF NOT EXISTS)
        up = uploader or build_uploader(settings)
        worker = SyncWorker(settings, up)
        app.state.settings = settings
        app.state.worker = worker
        task = asyncio.create_task(worker.run()) if start_worker else None
        target = settings.dry_run_dir if settings.sync_mode == "dry_run" else settings.supabase_url
        log.info("cloud-sync ready: data_dir=%s sync_mode=%s target=%s", settings.data_dir, settings.sync_mode, target)
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await up.aclose()

    app = FastAPI(title="ppe-cloud-sync", version="1.0.0", lifespan=lifespan)

    @app.get("/healthz")
    def healthz(request: Request):
        s: Settings = request.app.state.settings
        with db.connect(db.db_path(s.data_dir)) as conn:
            pending = store.pending_count(conn)
        return {
            "status": "ok",
            "sync_mode": s.sync_mode,
            "pending_upload": pending,
            "last_upload_at": request.app.state.worker.last_upload_at,
        }

    return app
