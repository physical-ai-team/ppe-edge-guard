"""COCO 사전학습 YOLOv8n을 ONNX로 export한다 (트랙 I1 임시 모델, 사람만 감지).

결과: gateway/models/yolov8n-coco-416-v1.onnx
가중치(yolov8n.pt)는 ultralytics가 공식 GitHub 릴리스에서 받는다.

실행 (ppe-training 환경):
    python training/export_coco_model.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "gateway" / "models"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--imgsz", type=int, default=416)
    args = ap.parse_args()
    version = f"yolov8n-coco-{args.imgsz}-v1"

    from ultralytics import YOLO

    work = Path(tempfile.mkdtemp(prefix="ppe-coco-"))
    model = YOLO(str(work / "yolov8n.pt"))  # 파일이 없으면 ultralytics가 받아서 이 경로에 둔다
    if model.names[0] != "person":
        print(f"[ERROR] class 0 is {model.names[0]!r}, expected 'person'", file=sys.stderr)
        return 1
    out = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=False,
                            dynamic=False, half=False))
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dst = MODELS_DIR / f"{version}.onnx"
    shutil.move(str(out), dst)
    shutil.rmtree(work, ignore_errors=True)
    print(f"[OK] {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
