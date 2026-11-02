"""export된 ONNX 모델을 inference 서비스와 같은 코드로 실행해 검증한다 (OpenCV 없음).

- 모델 로드·전처리·후처리·사람별 판정은 gateway/inference/app의 코드를 그대로 쓴다.
  (같은 로직을 두 군데 두지 않기 위해서. 서비스가 바뀌면 이 스크립트 결과도 같이 바뀐다)
- 사진마다 원본 클래스 검출, 사람별 판정(persons), summary를 출력한다.
- --compare <.pt 또는 .onnx>를 주면 같은 사진을 ultralytics로도 돌려 클래스 목록을 비교한다.
  같은 .onnx를 주면 전처리·후처리 구현이 ultralytics와 같은지 검사된다.

실행 (ppe-training 환경):
    python training/validate_onnx.py gateway/models/yolov8n-ppehf-640-v1.onnx <사진.jpg> [<사진2.jpg> ...]
    python training/validate_onnx.py <onnx> <사진.jpg> --compare <onnx>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "inference"))

from app.model import Detector, decode_jpeg  # noqa: E402
from app.ppe import judge  # noqa: E402
from app.yolo import letterbox, postprocess  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx", type=Path)
    ap.add_argument("images", type=Path, nargs="+")
    ap.add_argument("--classes", type=Path, default=ROOT / "gateway" / "models" / "classes.yaml")
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--compare", type=Path)
    args = ap.parse_args()

    det = Detector(args.onnx, args.classes, args.conf, args.iou, args.threads)
    names, canon = det.source_names, det.index_to_canonical
    print(f"model_version={det.model_version} imgsz={det.imgsz} classes={len(names)}")

    ref = None
    if args.compare:
        from ultralytics import YOLO
        ref = YOLO(str(args.compare), task="detect")

    for path in args.images:
        data = path.read_bytes()
        img = decode_jpeg(data)
        x, r, pad = letterbox(img, det.imgsz)
        det.session.run(None, {det.input_name: x})  # warm-up
        t0 = time.perf_counter()
        out = det.session.run(None, {det.input_name: x})[0]
        ms = (time.perf_counter() - t0) * 1000
        raw = postprocess(out, r, pad, img.size, args.conf, args.iou)

        print(f"\n== {path.name} {img.width}x{img.height}  model {ms:.1f} ms")
        for c, s, b in sorted(raw, key=lambda d: -d[1]):
            print(f"  {canon.get(c, '(제외)'):10s} {names[c]:15s} {s:.2f} {b}")
        persons, summary = judge(det.detect(data).detections, det.matching)
        for p in persons:
            print(f"  -> person {p['box']} helmet={p['helmet']} vest={p['vest']}")
        print(f"  summary: {summary}")

        if ref is not None:
            pr = ref.predict(str(path), imgsz=det.imgsz, conf=args.conf, iou=args.iou, verbose=False)[0]
            ref_cls = sorted(ref.names[int(c)] for c in pr.boxes.cls)
            our_cls = sorted(names[c] for c, _, _ in raw)
            ok = "일치" if ref_cls == our_cls else "불일치"
            print(f"  [compare] ultralytics {len(ref_cls)}개 / ours {len(our_cls)}개 → 클래스 목록 {ok}")
            if ref_cls != our_cls:
                print(f"    ultralytics: {ref_cls}\n    ours:        {our_cls}")


if __name__ == "__main__":
    main()
