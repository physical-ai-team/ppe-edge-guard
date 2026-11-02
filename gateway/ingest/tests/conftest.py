import io
import itertools
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from ppe_common.timeutil import to_iso, utcnow

TOKEN = "test-token"
CAPTURED_AT = utcnow() - timedelta(minutes=5)  # 미래 시각은 시계 오류로 처리되므로 현재 기준
CAPTURED_AT_ISO = to_iso(CAPTURED_AT)
_seq = itertools.count()


def make_jpeg(width: int = 640, height: int = 480, color=(90, 120, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def capture_headers(**overrides) -> dict:
    h = {
        "Content-Type": "image/jpeg",
        "X-Device-Id": "cam-test",
        "X-Device-Token": TOKEN,
        "X-Capture-Id": f"test-{next(_seq):06d}",
        "X-Captured-At": CAPTURED_AT_ISO,
        "X-Trigger": "serial",
    }
    for k, v in overrides.items():
        key = k.replace("_", "-")
        if v is None:
            h.pop(key, None)
        else:
            h[key] = v
    return h


def wait_status(client: TestClient, event_id: str, done=("compliant", "pending_upload", "infer_failed"), timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ev = client.get(f"/api/v1/events/{event_id}").json()
        if ev["status"] in done:
            return ev
        time.sleep(0.05)
    raise AssertionError(f"event {event_id} stuck in {ev['status']}")


@pytest.fixture
def make_settings(tmp_path):
    def _make(**kw) -> Settings:
        base = dict(device_token=TOKEN, data_dir=tmp_path, inference_mode="mock", mock_scenario="none_worn",
                    cleanup_interval_sec=3600, min_free_disk_mb=0)
        base.update(kw)
        return Settings(**base)
    return _make


@pytest.fixture
def make_client(make_settings):
    clients = []

    def _make(inference_client=None, **kw) -> TestClient:
        c = TestClient(create_app(make_settings(**kw), inference_client=inference_client))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
