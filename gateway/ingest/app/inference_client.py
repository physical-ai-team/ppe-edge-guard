"""ingest → inference 호출 (docs/interfaces.md ②).

INFERENCE_MODE=http : 실제 inference 컨테이너에 POST /infer
INFERENCE_MODE=mock : inference 없이 시나리오별 가짜 응답 (같은 응답 형식)
"""
import io
import random
from typing import Protocol

import httpx
from PIL import Image

from .config import Settings

SCENARIOS = ("both_worn", "helmet_only", "vest_only", "none_worn", "no_person")
_REQUIRED_SUMMARY = ("person_count", "missing_helmet", "missing_vest", "violation")


class InferenceError(Exception):
    """일시 오류 — 백오프 후 재시도."""


class PermanentInferenceError(Exception):
    """영구 오류(손상 이미지 등) — 재시도하지 않고 infer_failed."""


class InferenceClient(Protocol):
    async def infer(self, image: bytes, event_id: str) -> dict: ...
    async def aclose(self) -> None: ...


def validate_response(data: dict) -> dict:
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, dict) or any(k not in summary for k in _REQUIRED_SUMMARY):
        raise InferenceError(f"invalid inference response: {str(data)[:200]}")
    return data


class HttpInferenceClient:
    def __init__(self, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def infer(self, image: bytes, event_id: str) -> dict:
        try:
            r = await self._client.post(
                "/infer", content=image, headers={"Content-Type": "image/jpeg", "X-Event-Id": event_id}
            )
        except httpx.HTTPError as e:
            raise InferenceError(f"{type(e).__name__}: {e}") from e
        if r.status_code == 200:
            try:
                return validate_response(r.json())
            except ValueError as e:
                raise InferenceError(f"invalid JSON: {e}") from e
        if r.status_code == 400:
            raise PermanentInferenceError(f"400 {r.text[:200]}")
        raise InferenceError(f"{r.status_code} {r.text[:200]}")

    async def aclose(self) -> None:
        await self._client.aclose()


class MockInferenceClient:
    def __init__(self, scenario: str = "random", rng: random.Random | None = None):
        self.scenario = scenario
        self._rng = rng or random.Random()

    async def infer(self, image: bytes, event_id: str) -> dict:
        try:
            with Image.open(io.BytesIO(image)) as img:
                width, height = img.size
        except OSError as e:
            raise PermanentInferenceError(f"invalid_image: {e}") from e
        scenario = self._rng.choice(SCENARIOS) if self.scenario == "random" else self.scenario
        return build_mock_result(scenario, width, height, event_id, inference_ms=round(self._rng.uniform(5, 20), 1))

    async def aclose(self) -> None:
        pass


def build_mock_result(scenario: str, width: int, height: int, event_id: str, inference_ms: float = 10.0) -> dict:
    """시나리오 1인 기준 응답. 박스는 이미지 중앙에 대충 배치한다."""
    persons, detections = [], []
    if scenario != "no_person":
        helmet = "worn" if scenario in ("both_worn", "helmet_only") else "missing"
        vest = "worn" if scenario in ("both_worn", "vest_only") else "missing"
        x1, x2 = int(width * 0.35), int(width * 0.65)
        y1, y2 = int(height * 0.15), int(height * 0.95)
        person_box = [x1, y1, x2, y2]
        head_box = [int(width * 0.43), y1, int(width * 0.57), int(height * 0.28)]
        torso_box = [x1, int(height * 0.35), x2, int(height * 0.62)]
        persons.append({"box": person_box, "conf": 0.9, "helmet": helmet, "vest": vest})
        detections += [
            {"cls": "person", "conf": 0.9, "box": person_box},
            {"cls": "helmet" if helmet == "worn" else "no_helmet", "conf": 0.8, "box": head_box},
            {"cls": "vest" if vest == "worn" else "no_vest", "conf": 0.8, "box": torso_box},
        ]
    missing_helmet = any(p["helmet"] == "missing" for p in persons)
    missing_vest = any(p["vest"] == "missing" for p in persons)
    return {
        "event_id": event_id,
        "model_version": "mock-ppe-416-v1",
        "image": {"width": width, "height": height},
        "inference_ms": inference_ms,
        "persons": persons,
        "detections": detections,
        "summary": {
            "person_count": len(persons),
            "missing_helmet": missing_helmet,
            "missing_vest": missing_vest,
            "violation": missing_helmet or missing_vest,
            "unknown_helmet_count": 0,
            "unknown_vest_count": 0,
        },
        "mock_scenario": scenario,
    }


def build_client(settings: Settings) -> InferenceClient:
    if settings.inference_mode == "mock":
        return MockInferenceClient(settings.mock_scenario)
    return HttpInferenceClient(settings.inference_url, settings.infer_timeout_sec)
