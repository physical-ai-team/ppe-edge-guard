"""POST /api/v1/captures — docs/interfaces.md ① 계약 검사."""
import pytest

from app.images import MAX_IMAGE_BYTES
from conftest import CAPTURED_AT, CAPTURED_AT_ISO, capture_headers, make_jpeg, wait_status


def test_accepts_jpeg_and_returns_event_id(make_client):
    client = make_client()
    r = client.post("/api/v1/captures", content=make_jpeg(), headers=capture_headers())
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "received"
    assert body["event_id"].startswith(f"cam-test_{CAPTURED_AT:%Y%m%dT%H%M%SZ}_")
    assert len(body["event_id"].rsplit("_", 1)[1]) == 6


@pytest.mark.parametrize("missing", ["X-Device-Id", "X-Device-Token", "X-Capture-Id"])
def test_missing_required_header(make_client, missing):
    r = make_client().post("/api/v1/captures", content=make_jpeg(), headers=capture_headers(**{missing: None}))
    assert r.status_code == 400
    assert r.json()["error"] == "missing_header"


def test_invalid_token(make_client):
    r = make_client().post("/api/v1/captures", content=make_jpeg(), headers=capture_headers(**{"X-Device-Token": "nope"}))
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


@pytest.mark.parametrize("header,value", [
    ("X-Device-Id", "CAM_01"),
    ("X-Device-Id", "ab"),
    ("X-Capture-Id", "has space"),
    ("Content-Type", "image/png"),
])
def test_invalid_header(make_client, header, value):
    r = make_client().post("/api/v1/captures", content=make_jpeg(), headers=capture_headers(**{header: value}))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_header"


def test_not_a_jpeg(make_client):
    r = make_client().post("/api/v1/captures", content=b"hello world", headers=capture_headers())
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_image"


def test_too_large(make_client):
    big = make_jpeg() + b"\0" * MAX_IMAGE_BYTES
    r = make_client().post("/api/v1/captures", content=big, headers=capture_headers())
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"


def test_duplicate_capture_id_returns_200_same_event(make_client):
    client = make_client()
    headers = capture_headers()
    first = client.post("/api/v1/captures", content=make_jpeg(), headers=headers)
    second = client.post("/api/v1/captures", content=make_jpeg(), headers=headers)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == {"event_id": first.json()["event_id"], "status": "duplicate"}
    assert client.get("/api/v1/stats").json()["events"] == 1


def test_received_at_recorded_separately(make_client):
    client = make_client()
    event_id = client.post("/api/v1/captures", content=make_jpeg(), headers=capture_headers()).json()["event_id"]
    ev = client.get(f"/api/v1/events/{event_id}").json()
    assert ev["captured_at"] == CAPTURED_AT_ISO
    assert ev["clock_synced"] is True
    assert ev["received_at"].endswith("Z")
    assert ev["image"]["width"] == 640 and ev["image"]["height"] == 480


@pytest.mark.parametrize("captured_at", [None, "2099-01-01T00:00:00Z", "1970-01-01T00:00:10Z", "garbage"])
def test_missing_or_bad_clock_falls_back_to_received_at(make_client, captured_at):
    client = make_client()
    r = client.post("/api/v1/captures", content=make_jpeg(), headers=capture_headers(**{"X-Captured-At": captured_at}))
    assert r.status_code == 202  # 선택 헤더 오류로 사진을 버리지 않는다
    ev = client.get(f"/api/v1/events/{r.json()['event_id']}").json()
    assert ev["clock_synced"] is False
    assert ev["captured_at"] == ev["received_at"]


def test_bad_optional_headers_are_ignored(make_client):
    client = make_client()
    r = client.post("/api/v1/captures", content=make_jpeg(),
                    headers=capture_headers(**{"X-Trigger": "laser", "X-Detector-Score": "high"}))
    assert r.status_code == 202
    assert client.get(f"/api/v1/events/{r.json()['event_id']}").json()["trigger"] is None


def test_unknown_event_404(make_client):
    r = make_client().get("/api/v1/events/nope")
    assert r.status_code == 404


def test_healthz(make_client):
    assert make_client().get("/healthz").json() == {"status": "ok", "inference_mode": "mock"}


def test_image_saved_at_storage_path(make_client, tmp_path):
    client = make_client(mock_scenario="none_worn")
    event_id = client.post("/api/v1/captures", content=make_jpeg(), headers=capture_headers()).json()["event_id"]
    wait_status(client, event_id)
    assert (tmp_path / "images" / "cam-test" / f"{CAPTURED_AT:%Y/%m/%d}" / f"{event_id}.jpg").exists()
