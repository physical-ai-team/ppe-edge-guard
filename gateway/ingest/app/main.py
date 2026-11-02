"""ingest 서비스 진입점. 실행: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ppe_common import db
from ppe_common.logs import setup_logging
from ppe_common.timeutil import to_iso, utcnow

from . import store
from .api import router
from .cleanup import cleanup_loop, remove_stale_tmp
from .config import Settings
from .inference_client import InferenceClient, build_client
from .worker import InferenceWorker

log = logging.getLogger("ingest")


def create_app(settings: Settings | None = None, inference_client: InferenceClient | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        settings.images_dir.mkdir(parents=True, exist_ok=True)
        db_path = db.db_path(settings.data_dir)
        db.init_db(db_path)
        remove_stale_tmp(settings.images_dir)
        with db.connect(db_path) as conn:
            if n := store.reset_inferring(conn, to_iso(utcnow())):
                log.info("reset %d interrupted inference(s) to received", n)

        client = inference_client or build_client(settings)
        worker = InferenceWorker(settings, client)
        app.state.settings = settings
        app.state.worker = worker
        tasks = [asyncio.create_task(worker.run()), asyncio.create_task(cleanup_loop(settings))]
        log.info(
            "ingest ready: data_dir=%s inference_mode=%s debug_keep_compliant=%s max_images=%dMB",
            settings.data_dir, settings.inference_mode, settings.debug_keep_compliant, settings.local_image_max_mb,
        )
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            await client.aclose()

    app = FastAPI(title="ppe-ingest", version="1.0.0", lifespan=lifespan)
    app.include_router(router)
    return app
