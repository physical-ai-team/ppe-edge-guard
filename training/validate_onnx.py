"""export된 ONNX 모델을 numpy + Pillow + onnxruntime만으로 실행해 검증한다 (OpenCV 없음).

- 전처리·후처리(letterbox, NMS, 원본 좌표 복원)는 inference 컨테이너와 같은 방식으로 구현했다.
- classes.yaml로 정규화 5종 이름으로 바꿔 출력한다.
- --compare <.pt 또는 .onnx>를 주면 같은 이미지를 ultralytics로도 돌려 클래스 목록을 비교한다.
  같은 .onnx를 주면 전처리·후처리 구현이 ultralytics와 같은지 검사된다.

실행 (ppe-training 환경):
    python training/validate_onnx.py gateway/models/yolov8n-ppehf-416-v1.onnx <사진.jpg> [<사진2.jpg> ...]
    python training/validate_onnx.py <onnx> <사진.jpg> --compare <onnx>
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import yaml
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def resize_bilinear(a: np.ndarray, nw: int, nh: int) -> np.ndarray:
    """OpenCV INTER_LINEAR와 같은 bilinear 리사이즈 (안티앨리어싱 없음, half-pixel 중심).

    Pillow의 resize(BILINEAR)는 축소할 때 안티앨리어싱을 해서 YOLO 학습 때(OpenCV) 입력과 달라진다.
    이 모델은 그 차이에 민감하다(같은 사진에서 박스 3개 vs 10개). 그래서 직접 구현한다.
    """
    h, w = a.shape[:2]
    if (w, h) == (nw, nh):
        return a.astype(np.float32)

    def axis(n_out: int, n_in: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        src = (np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5
        src = np.clip(src, 0, n_in - 1)
        i0 = np.floor(src).astype(np.intp)
        i1 = np.minimum(i0 + 1, n_in - 1)
        return i0, i1, (src - i0).astype(np.float32)

    y0, y1, fy = axis(nh, h)
    x0, x1, fx = axis(nw, w)
    a = a.astype(np.float32)
    top = a[y0][:, x0] * (1 - fx)[None, :, None] + a[y0][:, x1] * fx[None, :, None]
    bot = a[y1][:, x0] * (1 - fx)[None, :, None] + a[y1][:, x1] * fx[None, :, None]
    return top * (1 - fy)[:, None, None] + bot * fy[:, None, None]


def letterbox(img: Image.Image, size: int) -> tuple[np.ndarray, float, tuple[int, int]]:
    """비율 유지 리사이즈 + 회색(114) 패딩 (ultralytics LetterBox와 같은 규칙).

    반환: (1,3,size,size) float32 RGB 0~1, 배율 r, (pad_x, pad_y)
    """
    w, h = img.size
    r = min(size / w, size / h)
    nw, nh = round(w * r), round(h * r)
    dw, dh = (size - nw) / 2, (size - nh) / 2
    px, py = round(dw - 0.1), round(dh - 0.1)
    resized = np.round(resize_bilinear(np.asarray(img), nw, nh)).clip(0, 255)  # uint8 반올림과 동일
    canvas = np.full((size, size, 3), 114, dtype=np.float32)
    canvas[py:py + nh, px:px + nw] = resized
    x = canvas.transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(x, dtype=np.float32), r, (px, py)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        ov = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][ov <= iou]
    return keep


def postprocess(out: np.ndarray, r: float, pad: tuple[int, int], orig: tuple[int, int],
                conf: float, iou: float) -> list[tuple[int, float, list[int]]]:
    """YOLOv8 출력 (1, 4+nc, N) → [(cls_idx, conf, [x1,y1,x2,y2] 원본 픽셀)]. 클래스별 NMS."""
    p = out[0].T  # (N, 4+nc)
    cls = p[:, 4:].argmax(1)
    sc = p[:, 4:].max(1)
    m = sc >= conf
    p, cls, sc = p[m], cls[m], sc[m]
    xy, wh = p[:, :2], p[:, 2:4]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1)
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad[0]) / r
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad[1]) / r
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, orig[0])
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, orig[1])
    res = []
    for c in np.unique(cls):
        idx = np.where(cls == c)[0]
        for k in nms(boxes[idx], sc[idx], iou):
            j = idx[k]
            res.append((int(c), float(sc[j]), [int(round(v)) for v in boxes[j]]))
    return res


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

    version = args.onnx.stem
    entry = yaml.safe_load(args.classes.read_text(encoding="utf-8"))["models"][version]
    names, canon, imgsz = entry["source_names"], entry["canonical"], entry["imgsz"]

    so = ort.SessionOptions()
    so.intra_op_num_threads = args.threads
    sess = ort.InferenceSession(str(args.onnx), so, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    print(f"model_version={version} input={inp.name}{inp.shape} output={sess.get_outputs()[0].shape}")
    assert inp.shape[2:] == [imgsz, imgsz], f"classes.yaml imgsz({imgsz}) != onnx {inp.shape}"

    pt_model = None
    if args.compare:
        from ultralytics import YOLO
        pt_model = YOLO(str(args.compare), task="detect")

    for path in args.images:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        x, r, pad = letterbox(img, imgsz)
        sess.run(None, {inp.name: x})  # warm-up
        t0 = time.perf_counter()
        out = sess.run(None, {inp.name: x})[0]
        ms = (time.perf_counter() - t0) * 1000
        dets = postprocess(out, r, pad, img.size, args.conf, args.iou)
        print(f"\n== {path.name} {img.size[0]}x{img.size[1]}  onnx {ms:.1f} ms")
        for c, s, b in sorted(dets, key=lambda d: -d[1]):
            raw = names[c]
            print(f"  {canon.get(raw, '(제외)'):10s} {raw:15s} {s:.2f} {b}")

        if pt_model is not None:
            pr = pt_model.predict(str(path), imgsz=imgsz, conf=args.conf, iou=args.iou,
                                  verbose=False)[0]
            pt_cls = sorted(pt_model.names[int(c)] for c in pr.boxes.cls)
            onnx_cls = sorted(names[c] for c, _, _ in dets)
            ok = "일치" if pt_cls == onnx_cls else "불일치"
            print(f"  [compare] pt {len(pt_cls)}개 / onnx {len(onnx_cls)}개 → 클래스 목록 {ok}")
            if pt_cls != onnx_cls:
                print(f"    pt:   {pt_cls}\n    onnx: {onnx_cls}")


if __name__ == "__main__":
    main()
