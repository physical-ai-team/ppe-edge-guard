"""HTTP API + ② 계약 형식. 실제 ONNX가 gateway/models에 있으면 실제 모델로도 검사한다."""
import pytest

from conftest import MODELS_DIR, FakeDetector, assert_contract, make_jpeg

HEADERS = {"Content-Type": "image/jpeg", "X-Event-Id": "cam-01_20261102T053112Z_a1b2c3"}


def test_infer_contract_with_fake_detector(make_client):
    dets = [
        {"cls": "person", "conf": 0.91, "box": [100, 100, 300, 460]},
        {"cls": "no_helmet", "conf": 0.77, "box": [160, 95, 240, 160]},
        {"cls": "vest", "conf": 0.81, "box": [120, 200, 280, 330]},
    ]
    c = make_client(FakeDetector(dets))
    r = c.post("/infer", content=make_jpeg(640, 480), headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert_contract(body, 640, 480)
    assert body["event_id"] == HEADERS["X-Event-Id"]
    assert body["persons"] == [{"box": [100, 100, 300, 460], "conf": 0.91, "helmet": "missing", "vest": "worn"}]
    assert body["summary"]["violation"] is True


def test_event_id_optional(make_client):
    c = make_client(FakeDetector())
    r = c.post("/infer", content=make_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200
    assert r.json()["event_id"] is None
    assert r.json()["summary"]["person_count"] == 0


@pytest.mark.parametrize("payload", [b"", b"not a jpeg", b"\xff\xd8\xff\xe0garbage"])
def test_invalid_image_400(make_client, payload):
    c = make_client(FakeDetector())
    r = c.post("/infer", content=payload, headers=HEADERS)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_image"


def test_png_rejected(make_client):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    r = make_client(FakeDetector()).post("/infer", content=buf.getvalue(), headers=HEADERS)
    assert r.status_code == 400


def test_too_large_400(make_client):
    c = make_client(FakeDetector(), max_image_mb=0.001)
    r = c.post("/infer", content=make_jpeg(640, 480, (1, 2, 3)) + b"\0" * 2000, headers=HEADERS)
    assert r.status_code == 400


def test_healthz_ok(make_client):
    r = make_client(FakeDetector()).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model_loaded": True, "model_version": "fake-ppe-416-v1", "imgsz": 416}


def test_model_missing_503(make_client, tmp_path):
    c = make_client(None, model_path=tmp_path / "nope-416-v1.onnx", model_classes=MODELS_DIR / "classes.yaml")
    r = c.get("/healthz")
    assert r.status_code == 503 and r.json()["model_loaded"] is False
    r = c.post("/infer", content=make_jpeg(), headers=HEADERS)
    assert r.status_code == 503 and r.json()["error"] == "model_not_loaded"


# ---------- 실제 모델 (파일이 있을 때만) ----------
REAL_MODELS = sorted(MODELS_DIR.glob("*.onnx"))


@pytest.mark.skipif(not REAL_MODELS, reason="gateway/models/*.onnx 없음 (training/export_*.py로 생성)")
@pytest.mark.parametrize("model_path", REAL_MODELS, ids=lambda p: p.stem)
def test_real_model_contract(make_client, model_path):
    c = make_client(None, model_path=model_path, model_classes=MODELS_DIR / "classes.yaml")
    h = c.get("/healthz")
    assert h.status_code == 200, h.json()
    assert h.json()["model_version"] == model_path.stem

    # 사람 없는 단색 사진 → no_person 시나리오
    r = c.post("/infer", content=make_jpeg(1280, 1024), headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert_contract(body, 1280, 1024)
    assert body["model_version"] == model_path.stem
    assert body["summary"]["person_count"] == 0 and body["summary"]["violation"] is False

    # 흑백 JPEG도 받는다
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (320, 240), 128).save(buf, "JPEG")
    r = c.post("/infer", content=buf.getvalue(), headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["image"] == {"width": 320, "height": 240}
