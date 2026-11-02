"""ONNX 모델 로드 + 추론 → 정규화 클래스 검출 목록.

- model_version = MODEL_PATH 파일명(확장자 제외). classes.yaml의 models.<model_version> 항목을 쓴다.
- 원본 클래스 이름은 ONNX 메타데이터(ultralytics export가 기록하는 names)에서 읽는다.
  classes.yaml에 source_names가 있으면 이름·순서가 같은지 검사한다.
- 입력 크기는 ONNX 입력 shape(고정)를 따른다.
"""
from __future__ import annotations

import ast
import io
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
import yaml
from PIL import Image

from .ppe import Matching
from .yolo import letterbox, postprocess

log = logging.getLogger("inference.model")

CANONICAL = {"person", "helmet", "no_helmet", "vest", "no_vest"}
MAX_PIXELS = 4096 * 4096  # 디코드 폭탄 방어 (ESP32 최대 해상도보다 충분히 큼)


class ModelLoadError(Exception):
    pass


class InvalidImage(Exception):
    pass


@dataclass
class DetectResult:
    width: int
    height: int
    detections: list[dict]  # [{cls, conf, box}] 정규화 이름만
    timings_ms: dict[str, float]


def load_class_config(classes_path: Path, model_version: str) -> tuple[dict, Matching]:
    try:
        cfg = yaml.safe_load(classes_path.read_text(encoding="utf-8")) or {}
    except OSError as e:
        raise ModelLoadError(f"cannot read {classes_path}: {e}") from e
    entry = (cfg.get("models") or {}).get(model_version)
    if entry is None:
        raise ModelLoadError(f"{classes_path}: no entry for model_version '{model_version}'")
    canonical = entry.get("canonical") or {}
    bad = set(canonical.values()) - CANONICAL
    if bad:
        raise ModelLoadError(f"{model_version}: unknown canonical names {sorted(bad)}")
    matching = Matching.from_dict({**(cfg.get("matching") or {}), **(entry.get("matching") or {})})
    return entry, matching


def decode_jpeg(data: bytes) -> Image.Image:
    if not data.startswith(b"\xff\xd8"):
        raise InvalidImage("not a JPEG (missing FF D8)")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format != "JPEG":
            raise InvalidImage(f"not a JPEG ({img.format})")
        if img.width * img.height > MAX_PIXELS:
            raise InvalidImage(f"image too large ({img.width}x{img.height})")
        img.load()
    except InvalidImage:
        raise
    except Exception as e:  # Pillow는 손상 파일에서 OSError 외 예외도 낸다
        raise InvalidImage(f"decode failed: {type(e).__name__}: {e}") from e
    # EXIF 회전은 적용하지 않는다: 박스 좌표 = ingest가 기록한 원본 width/height 기준 (ESP32 JPEG에는 EXIF 회전 없음)
    return img.convert("RGB") if img.mode != "RGB" else img


class Detector:
    def __init__(self, model_path: Path, classes_path: Path, conf: float, iou: float,
                 num_threads: int = 3, expected_imgsz: int | None = None):
        self.model_version = model_path.stem
        self.conf, self.iou = conf, iou
        if not model_path.is_file():
            raise ModelLoadError(f"model file not found: {model_path}")
        entry, self.matching = load_class_config(classes_path, self.model_version)

        so = ort.SessionOptions()
        so.intra_op_num_threads = num_threads
        so.inter_op_num_threads = 1
        try:
            self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        except Exception as e:
            raise ModelLoadError(f"onnxruntime load failed: {e}") from e

        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        if len(shape) != 4 or not all(isinstance(s, int) for s in shape[2:]) or shape[2] != shape[3]:
            raise ModelLoadError(f"need a static square input (1,3,N,N), got {shape}")
        self.imgsz = int(shape[2])
        if expected_imgsz and expected_imgsz != self.imgsz:
            log.warning("INFER_IMGSZ=%d but model input is %d — using model input", expected_imgsz, self.imgsz)

        names = self._read_names(entry)
        canonical = entry.get("canonical") or {}
        missing = set(canonical) - set(names)
        if missing:
            raise ModelLoadError(f"classes.yaml maps names the model doesn't have: {sorted(missing)}")
        self.source_names = names
        self.index_to_canonical = {i: canonical[n] for i, n in enumerate(names) if n in canonical}
        self._lock = threading.Lock()  # 동시 요청이 와도 CPU 스레드를 과하게 쓰지 않게 한 번에 하나씩

        # 워밍업: 첫 요청 지연(수백 ms)을 없애고, 모델이 실제로 돌아가는지 로드 시점에 확인한다
        try:
            self.session.run(None, {self.input_name: np.zeros((1, 3, self.imgsz, self.imgsz), np.float32)})
        except Exception as e:
            raise ModelLoadError(f"warm-up inference failed: {e}") from e
        log.info("model loaded: %s imgsz=%d classes=%d mapped=%s", self.model_version, self.imgsz,
                 len(names), sorted(set(self.index_to_canonical.values())))

    def _read_names(self, entry: dict) -> list[str]:
        meta = self.session.get_modelmeta().custom_metadata_map
        names: list[str] | None = None
        if "names" in meta:
            d = ast.literal_eval(meta["names"])  # "{0: 'Hardhat', ...}" — 리터럴만 허용
            names = [d[i] for i in sorted(d)]
        expected = entry.get("source_names")
        if names is None:
            if not expected:
                raise ModelLoadError("no class names in ONNX metadata and no source_names in classes.yaml")
            names = list(expected)
        elif expected and list(expected) != names:
            raise ModelLoadError(f"class names/order mismatch\n  classes.yaml: {expected}\n  onnx: {names}")
        return names

    def detect(self, data: bytes) -> DetectResult:
        t0 = time.perf_counter()
        img = decode_jpeg(data)
        x, r, pad = letterbox(img, self.imgsz)
        t1 = time.perf_counter()
        with self._lock:
            out = self.session.run(None, {self.input_name: x})[0]
        t2 = time.perf_counter()
        raw = postprocess(np.asarray(out), r, pad, img.size, self.conf, self.iou,
                          keep_classes=set(self.index_to_canonical))
        dets = [{"cls": self.index_to_canonical[c], "conf": round(s, 3), "box": b} for c, s, b in raw]
        t3 = time.perf_counter()
        timings = {"pre": (t1 - t0) * 1000, "model": (t2 - t1) * 1000, "post": (t3 - t2) * 1000}
        return DetectResult(img.width, img.height, dets, timings)
