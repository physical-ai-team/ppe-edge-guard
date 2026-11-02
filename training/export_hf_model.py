"""Hugging Face 공개 PPE 모델(best.pt)을 받아 ONNX로 export한다.

대상: https://huggingface.co/Hansung-Cho/yolov8-ppe-detection (MIT, YOLOv8n)
- 리비전을 고정해서 받는다 (다른 사람이 실행해도 같은 파일).
- 체크포인트의 클래스 이름이 classes.yaml의 source_names와 같은지 검사한다.
- 결과: gateway/models/{model_version}.onnx

실행 (ppe-training 환경):
    python training/export_hf_model.py               # → yolov8n-ppehf-640-v1.onnx (기본값)
    python training/export_hf_model.py --imgsz 416   # → yolov8n-ppehf-416-v1.onnx (비교용)
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

import yaml

REPO_ID = "Hansung-Cho/yolov8-ppe-detection"
REVISION = "ac0027bd38bc619d5ce4f52b4cc01beb87d8b958"  # 2025-11-27
FILENAME = "best.pt"
SHA256 = "2419700bbe3b8d38f9000655d9cf952a4bc93ef6c143baf8b49a0abde5d0760f"

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "gateway" / "models"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download() -> Path:
    """고정 리비전의 best.pt를 캐시 폴더로 받는다 (이미 있으면 재사용). 레포 밖에 둔다."""
    cache = Path.home() / ".cache" / "ppe-edge-guard" / REVISION[:12]
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / FILENAME
    if not dst.exists():
        url = f"https://huggingface.co/{REPO_ID}/resolve/{REVISION}/{FILENAME}"
        print(f"download {url}")
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--version", default=None, help="기본값: yolov8n-ppehf-{imgsz}-v1")
    ap.add_argument("--classes", type=Path, default=MODELS_DIR / "classes.yaml")
    args = ap.parse_args()
    version = args.version or f"yolov8n-ppehf-{args.imgsz}-v1"

    from ultralytics import YOLO

    pt = download()
    digest = sha256(pt)
    if digest != SHA256:
        print(f"[ERROR] sha256 불일치: {digest}", file=sys.stderr)
        return 1

    model = YOLO(str(pt))
    names = [model.names[i] for i in sorted(model.names)]
    train_args = model.ckpt.get("train_args", {}) if isinstance(model.ckpt, dict) else {}
    print(f"classes ({len(names)}): {names}")
    print(f"train imgsz: {train_args.get('imgsz')}, epochs: {train_args.get('epochs')}")

    cfg = yaml.safe_load(args.classes.read_text(encoding="utf-8"))
    entry = cfg["models"].get(version)
    if entry is None:
        print(f"[ERROR] {args.classes}에 '{version}' 항목이 없다", file=sys.stderr)
        return 1
    if entry["source_names"] != names:
        print(f"[ERROR] 클래스 이름/순서 불일치\n  yaml: {entry['source_names']}\n  pt:   {names}",
              file=sys.stderr)
        return 1

    out = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=False,
                            dynamic=False, half=False))
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dst = MODELS_DIR / f"{version}.onnx"
    shutil.move(str(out), dst)
    print(f"[OK] {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
