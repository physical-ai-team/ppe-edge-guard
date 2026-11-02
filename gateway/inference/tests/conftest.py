import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.model import DetectResult, decode_jpeg
from app.ppe import Matching

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
CANONICAL = {"person", "helmet", "no_helmet", "vest", "no_vest"}
STATES = {"worn", "missing", "unknown"}


def make_jpeg(width: int = 640, height: int = 480, color=(90, 120, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


class FakeDetector:
    """고정 검출 결과를 돌려주는 가짜 모델 (API·계약 테스트용)."""

    model_version = "fake-ppe-416-v1"
    imgsz = 416
    matching = Matching()

    def __init__(self, detections: list[dict] | None = None):
        self.detections = detections or []

    def detect(self, data: bytes) -> DetectResult:
        img = decode_jpeg(data)
        return DetectResult(img.width, img.height, list(self.detections), {"pre": 1.0, "model": 1.0, "post": 1.0})


@pytest.fixture
def make_client():
    clients = []

    def _make(detector=None, **settings) -> TestClient:
        s = Settings(**settings)
        c = TestClient(create_app(s, detector=detector))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def assert_contract(body: dict, width: int, height: int) -> None:
    """docs/interfaces.md ② 응답 형식 검사."""
    assert set(body) >= {"event_id", "model_version", "image", "inference_ms", "persons", "detections", "summary"}
    assert isinstance(body["model_version"], str) and body["model_version"]
    assert body["image"] == {"width": width, "height": height}
    assert isinstance(body["inference_ms"], (int, float)) and body["inference_ms"] >= 0

    def check_box(b):
        assert isinstance(b, list) and len(b) == 4 and all(isinstance(v, int) for v in b)
        assert 0 <= b[0] <= b[2] <= width and 0 <= b[1] <= b[3] <= height

    for d in body["detections"]:
        assert d["cls"] in CANONICAL
        assert 0 <= d["conf"] <= 1
        check_box(d["box"])
    for p in body["persons"]:
        assert set(p) == {"box", "conf", "helmet", "vest"}
        assert p["helmet"] in STATES and p["vest"] in STATES
        check_box(p["box"])

    s = body["summary"]
    assert set(s) == {"person_count", "missing_helmet", "missing_vest", "violation",
                      "unknown_helmet_count", "unknown_vest_count"}
    assert s["person_count"] == len(body["persons"])
    assert s["violation"] == (s["missing_helmet"] or s["missing_vest"])
    assert s["unknown_helmet_count"] == sum(p["helmet"] == "unknown" for p in body["persons"])
    assert s["unknown_vest_count"] == sum(p["vest"] == "unknown" for p in body["persons"])
    if any(p["helmet"] == "missing" for p in body["persons"]):
        assert s["missing_helmet"]
    if any(p["vest"] == "missing" for p in body["persons"]):
        assert s["missing_vest"]
