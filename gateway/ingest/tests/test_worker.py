"""received → inference → compliant / pending_upload 상태 전이, 재시도, 사진 삭제 정책."""
import time

import httpx
import pytest

from app.inference_client import HttpInferenceClient, build_mock_result
from conftest import CAPTURED_AT, capture_headers, make_jpeg, wait_status


def _post(client, **headers):
    r = client.post("/api/v1/captures", content=make_jpeg(), headers=capture_headers(**headers))
    assert r.status_code == 202
    return r.json()["event_id"]


def _image_file(tmp_path, event_id):
    return tmp_path / "images" / "cam-test" / f"{CAPTURED_AT:%Y/%m/%d}" / f"{event_id}.jpg"


@pytest.mark.parametrize("scenario,status,helmet,vest", [
    ("both_worn", "compliant", False, False),
    ("helmet_only", "pending_upload", False, True),
    ("vest_only", "pending_upload", True, False),
    ("none_worn", "pending_upload", True, True),
    ("no_person", "compliant", False, False),
])
def test_mock_scenarios(make_client, scenario, status, helmet, vest):
    client = make_client(mock_scenario=scenario)
    ev = wait_status(client, _post(client))
    assert ev["status"] == status
    s = ev["result"]["summary"]
    assert (s["missing_helmet"], s["missing_vest"]) == (helmet, vest)
    assert ev["result"]["mock_scenario"] == scenario


def test_compliant_image_deleted_by_default(make_client, tmp_path):
    client = make_client(mock_scenario="both_worn")
    event_id = _post(client)
    ev = wait_status(client, event_id)
    assert ev["image"]["deleted"] is True
    assert not _image_file(tmp_path, event_id).exists()


def test_compliant_image_kept_in_debug_mode(make_client, tmp_path):
    client = make_client(mock_scenario="both_worn", debug_keep_compliant=True)
    event_id = _post(client)
    ev = wait_status(client, event_id)
    assert ev["image"]["deleted"] is False
    assert _image_file(tmp_path, event_id).exists()


def test_violation_image_kept(make_client, tmp_path):
    client = make_client(mock_scenario="none_worn")
    event_id = _post(client)
    wait_status(client, event_id)
    assert _image_file(tmp_path, event_id).exists()


def _http_client(handler):
    return HttpInferenceClient("http://inference:8001", 5, transport=httpx.MockTransport(handler))


def test_http_mode_sends_contract_request(make_client):
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["ctype"] = request.headers["content-type"]
        seen["event_id"] = request.headers["x-event-id"]
        seen["body"] = request.content[:2]
        return httpx.Response(200, json=build_mock_result("helmet_only", 640, 480, request.headers["x-event-id"]))

    client = make_client(inference_client=_http_client(handler), inference_mode="http")
    event_id = _post(client)
    ev = wait_status(client, event_id)
    assert ev["status"] == "pending_upload"
    assert seen == {"path": "/infer", "ctype": "image/jpeg", "event_id": event_id, "body": b"\xff\xd8"}


def test_http_transient_error_retries_then_succeeds(make_client):
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "model_not_loaded"})
        return httpx.Response(200, json=build_mock_result("both_worn", 640, 480, "x"))

    client = make_client(inference_client=_http_client(handler), inference_mode="http")
    ev = wait_status(client, _post(client), timeout=6)
    assert ev["status"] == "compliant"
    assert ev["infer_attempts"] == 2
    assert calls["n"] == 2


def test_http_400_marks_infer_failed(make_client):
    client = make_client(
        inference_client=_http_client(lambda r: httpx.Response(400, json={"error": "invalid_image"})),
        inference_mode="http",
    )
    ev = wait_status(client, _post(client))
    assert ev["status"] == "infer_failed"
    assert "400" in ev["last_error"]


def test_invalid_inference_response_is_retried(make_client):
    client = make_client(
        inference_client=_http_client(lambda r: httpx.Response(200, json={"oops": True})), inference_mode="http"
    )
    event_id = _post(client)
    time.sleep(0.5)
    ev = client.get(f"/api/v1/events/{event_id}").json()
    assert ev["status"] == "received"
    assert "invalid inference response" in ev["last_error"]


def test_stats_counts_unknown(make_client):
    def handler(request):
        result = build_mock_result("both_worn", 640, 480, "x")
        result["persons"][0]["vest"] = "unknown"
        result["summary"]["unknown_vest_count"] = 1
        return httpx.Response(200, json=result)

    client = make_client(inference_client=_http_client(handler), inference_mode="http")
    wait_status(client, _post(client))
    wait_status(client, _post(client, **{"X-Device-Id": "cam-other"}))
    stats = client.get("/api/v1/stats").json()
    assert stats["events"] == 2
    assert stats["persons"] == 2
    assert stats["unknown_vest_count"] == 2
    assert stats["unknown_vest_rate"] == 1.0
    assert stats["by_status"] == {"compliant": 2}
    assert stats["by_model_version"] == {"mock-ppe-416-v1": 2}
    assert client.get("/api/v1/stats", params={"device_id": "cam-other"}).json()["events"] == 1
    assert client.get("/api/v1/stats", params={"since": "2999-01-01T00:00:00Z"}).json()["events"] == 0
    assert client.get("/api/v1/stats", params={"since": "yesterday"}).status_code == 400
