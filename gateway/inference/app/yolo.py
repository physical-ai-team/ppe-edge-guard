"""YOLOv8 ONNX 전처리·후처리 (numpy + Pillow, OpenCV 없음).

ultralytics(학습·검증에 쓰는 OpenCV 경로)와 같은 결과가 나오도록 맞췄다.
training/validate_onnx.py도 이 모듈을 그대로 import해서 쓴다.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

PAD_VALUE = 114


def resize_bilinear(a: np.ndarray, nw: int, nh: int) -> np.ndarray:
    """OpenCV INTER_LINEAR와 같은 bilinear 리사이즈 (안티앨리어싱 없음, half-pixel 중심). float32 반환.

    Pillow resize(BILINEAR)는 축소할 때 안티앨리어싱을 해서 학습 때(OpenCV) 입력과 달라진다.
    이 모델은 그 차이에 민감하다(같은 사진에서 박스 3개 vs 10개).
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
    fx3 = fx[None, :, None]
    top = a[y0][:, x0] * (1 - fx3) + a[y0][:, x1] * fx3
    bot = a[y1][:, x0] * (1 - fx3) + a[y1][:, x1] * fx3
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
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.float32)
    canvas[py:py + nh, px:px + nw] = resized
    x = canvas.transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(x, dtype=np.float32), r, (px, py)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    """단순 greedy NMS. 점수 높은 순으로 남긴 인덱스."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        ov = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[ov <= iou]
    return keep


def postprocess(out: np.ndarray, r: float, pad: tuple[int, int], orig: tuple[int, int],
                conf: float, iou: float, keep_classes: set[int] | None = None,
                ) -> list[tuple[int, float, list[int]]]:
    """YOLOv8 출력 (1, 4+nc, N) → [(cls_idx, conf, [x1,y1,x2,y2] 원본 픽셀)]. 클래스별 NMS.

    keep_classes를 주면 그 클래스만 남긴다 (NMS 전에 걸러서 불필요한 계산을 줄임).
    """
    p = out[0].T  # (N, 4+nc)
    scores = p[:, 4:]
    cls = scores.argmax(1)
    sc = scores.max(1)
    m = sc > conf
    if keep_classes is not None:
        m &= np.isin(cls, list(keep_classes))
    p, cls, sc = p[m], cls[m], sc[m]
    if not len(p):
        return []
    xy, wh = p[:, :2], p[:, 2:4]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1)
    boxes[:, [0, 2]] = ((boxes[:, [0, 2]] - pad[0]) / r).clip(0, orig[0])
    boxes[:, [1, 3]] = ((boxes[:, [1, 3]] - pad[1]) / r).clip(0, orig[1])
    res = []
    for c in np.unique(cls):
        idx = np.where(cls == c)[0]
        for k in nms(boxes[idx], sc[idx], iou):
            j = idx[k]
            res.append((int(c), float(sc[j]), [int(round(v)) for v in boxes[j]]))
    return res
