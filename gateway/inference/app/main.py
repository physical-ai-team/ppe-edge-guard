"""inference 서비스 (docs/interfaces.md ②). 무상태: JPEG 바이트를 받아 판정 결과를 돌려준다.

실행: uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8001

모델 로드에 실패해도 서비스는 뜬다. 이때 /healthz와 /infer는 503(model_not_loaded)을 돌려주고,
ingest는 일시 오류로 보고 재시도한다. 모델 파일을 넣은 뒤 컨테이너를 재시작하면 된다.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ppe_common.logs import setup_logging

from .config import Settings
from .model import Detector, InvalidImage, ModelLoadError
from .ppe import judge

log = logging.getLogger("inference")


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


def create_app(settings: Settings | None = None, detector: Detector | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        app.state.detector = detector
        app.state.load_error = None
        if detector is None:
            try:
                app.state.detector = Detector(
                    settings.model_path, settings.model_classes, settings.conf_threshold,
                    settings.iou_threshold, settings.ort_num_threads, settings.infer_imgsz,
                )
            except ModelLoadError as e:
                app.state.load_error = str(e)
                log.error("model not loaded: %s", e)
        yield

    app = FastAPI(title="ppe-inference", version="1.0.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz(request: Request):
        det: Detector | None = request.app.state.detector
        if det is None:
            return JSONResponse(
                {"status": "error", "model_loaded": False, "model_version": None, "imgsz": None,
                 "detail": request.app.state.load_error},
                status_code=503,
            )
        return {"status": "ok", "model_loaded": True, "model_version": det.model_version, "imgsz": det.imgsz}

    @app.post("/infer")
    async def infer(request: Request):
        det: Detector | None = request.app.state.detector
        if det is None:
            return _error(503, "model_not_loaded", request.app.state.load_error or "model not loaded")
        event_id = request.headers.get("x-event-id") or None
        body = await request.body()
        if len(body) > settings.max_image_bytes:
            return _error(400, "invalid_image", f"image larger than {settings.max_image_mb} MB")

        t0 = time.perf_counter()
        try:
            res = await run_in_threadpool(det.detect, body)
        except InvalidImage as e:
            log.warning("event %s: invalid image: %s", event_id, e)
            return _error(400, "invalid_image", str(e))
        persons, summary = judge(res.detections, det.matching)
        ms = round((time.perf_counter() - t0) * 1000, 1)

        log.info(
            "event %s: %dx%d persons=%d violation=%s helmet_missing=%s vest_missing=%s %.0fms "
            "(pre %.0f / model %.0f / post %.0f)",
            event_id, res.width, res.height, summary["person_count"], summary["violation"],
            summary["missing_helmet"], summary["missing_vest"], ms,
            res.timings_ms["pre"], res.timings_ms["model"], res.timings_ms["post"],
        )
        return {
            "event_id": event_id,
            "model_version": det.model_version,
            "image": {"width": res.width, "height": res.height},
            "inference_ms": ms,
            "persons": persons,
            "detections": res.detections,
            "summary": summary,
        }

    return app
