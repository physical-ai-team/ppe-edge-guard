"""전처리·후처리 (ultralytics/OpenCV와 같은 결과)."""
import numpy as np
import pytest
from PIL import Image

from app.yolo import letterbox, nms, postprocess, resize_bilinear


def test_resize_downscale_by_two_is_block_average():
    a = np.arange(16, dtype=np.float32).reshape(4, 4, 1).repeat(3, axis=2)
    out = resize_bilinear(a, 2, 2)
    assert out.shape == (2, 2, 3)
    expect = np.array([[2.5, 4.5], [10.5, 12.5]], dtype=np.float32)
    np.testing.assert_allclose(out[..., 0], expect)


def test_resize_identity():
    a = np.random.default_rng(0).integers(0, 255, (5, 7, 3)).astype(np.uint8)
    np.testing.assert_array_equal(resize_bilinear(a, 7, 5), a.astype(np.float32))


def test_resize_matches_opencv():
    cv2 = pytest.importorskip("cv2")  # inference 환경에는 없음. ppe-training 환경에서 확인
    rng = np.random.default_rng(1)
    a = rng.integers(0, 255, (853, 1280, 3)).astype(np.uint8)
    ours = np.round(resize_bilinear(a, 416, 277)).astype(np.uint8)
    ref = cv2.resize(a, (416, 277), interpolation=cv2.INTER_LINEAR)
    assert np.abs(ours.astype(int) - ref.astype(int)).max() <= 1  # OpenCV 고정소수점 반올림 차이


def test_letterbox_padding_and_ratio():
    img = Image.new("RGB", (1280, 853), (200, 10, 10))
    x, r, pad = letterbox(img, 416)
    assert x.shape == (1, 3, 416, 416) and x.dtype == np.float32
    assert r == pytest.approx(0.325)
    assert pad == (0, 69)
    assert x[0, :, 0, 0] == pytest.approx([114 / 255] * 3)       # 위쪽 패딩
    assert x[0, :, 200, 200] == pytest.approx([200 / 255, 10 / 255, 10 / 255])


def test_nms_suppresses_overlaps():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.45) == [0, 2]


def test_postprocess_maps_back_to_original_pixels():
    # 1280x853 원본, 416 입력: r=0.325, pad=(0,69). 원본 [100,200,300,400] 박스 하나 (클래스 1)
    r, pad = 0.325, (0, 69)
    x1, y1, x2, y2 = (np.array([100, 200, 300, 400]) * r + [0, 69, 0, 69])
    out = np.zeros((1, 4 + 3, 2), dtype=np.float32)
    out[0, :4, 0] = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
    out[0, 4 + 1, 0] = 0.9
    out[0, 4 + 2, 1] = 0.3  # 임계값 미만 → 제외
    res = postprocess(out, r, pad, (1280, 853), conf=0.4, iou=0.45)
    assert res == [(1, pytest.approx(0.9), [100, 200, 300, 400])]
    assert postprocess(out, r, pad, (1280, 853), 0.4, 0.45, keep_classes={0, 2}) == []
