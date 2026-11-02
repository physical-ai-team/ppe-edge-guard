"""시나리오 영상으로 모델별 판정 정확도를 비교한다 (예: 416 vs 640, 결과는 gateway/models/README.md).

영상 파일 이름의 앞부분이 정답 라벨이다 (docs/dev-testing.md):
    both_worn_* / helmet_only_* / vest_only_* / none_worn_* / no_person_*  → 정확도 계산
    그 외 (multi_2p_*, mixed_* 등)                                         → 결과만 출력

- 프레임을 --fps 간격으로 뽑고, ESP32 사진 조건에 가깝게 맞춘다
  (긴 변 --max-side 이하로 축소, JPEG --jpeg-quality로 다시 압축).
- 판정은 inference 서비스 코드(gateway/inference/app)를 그대로 쓴다.
- 결과: 터미널 표 + --out 폴더에 프레임별 CSV(+ --save-frames면 JPEG). 영상·프레임은 git 밖에 둔다.

실행 (ppe-training 환경, 영상 읽기에 OpenCV 사용 — 학습·평가 도구라 허용):
    python training/eval_scenarios.py <영상 또는 폴더> --models yolov8n-ppehf-416-v1 yolov8n-ppehf-640-v1 --out <git 밖 폴더>
"""

from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "inference"))

import cv2  # noqa: E402
from PIL import Image  # noqa: E402

from app.model import Detector  # noqa: E402
from app.ppe import judge  # noqa: E402

# 시나리오 → (helmet 정답, vest 정답, violation 정답). None = 사람 없음
SCENARIOS = {
    "both_worn": ("worn", "worn", False),
    "helmet_only": ("worn", "missing", True),
    "vest_only": ("missing", "worn", True),
    "none_worn": ("missing", "missing", True),
    "no_person": (None, None, False),
}


def scenario_of(path: Path) -> str | None:
    return next((s for s in SCENARIOS if path.stem.startswith(s + "_")), None)


def extract_frames(video: Path, fps: float, max_side: int, quality: int) -> list[tuple[float, bytes]]:
    cap = cv2.VideoCapture(str(video))
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(vfps / fps))
    frames, i = [], 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        if i % step == 0:
            img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality)
            frames.append((i / vfps, buf.getvalue()))
        i += 1
    cap.release()
    return frames


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:5.1f}%" if d else "    -"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", type=Path, nargs="+", help="영상 파일 또는 폴더(*.mp4)")
    ap.add_argument("--models", nargs="+", default=["yolov8n-ppehf-416-v1", "yolov8n-ppehf-640-v1"])
    ap.add_argument("--models-dir", type=Path, default=ROOT / "gateway" / "models")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--max-side", type=int, default=1280)
    ap.add_argument("--jpeg-quality", type=int, default=80)
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--out", type=Path, help="프레임별 CSV(와 프레임 JPEG) 저장 폴더 (git 밖)")
    ap.add_argument("--save-frames", action="store_true")
    args = ap.parse_args()

    videos = sorted(p for i in args.inputs for p in ([i] if i.is_file() else i.glob("*.mp4")))
    detectors = {m: Detector(args.models_dir / f"{m}.onnx", args.models_dir / "classes.yaml",
                             args.conf, args.iou) for m in args.models}
    rows = []

    for video in videos:
        scen = scenario_of(video)
        frames = extract_frames(video, args.fps, args.max_side, args.jpeg_quality)
        print(f"\n### {video.name}  scenario={scen or '(라벨 없음)'}  frames={len(frames)}")
        if args.out and args.save_frames:
            fdir = args.out / "frames" / video.stem
            fdir.mkdir(parents=True, exist_ok=True)
            for t, data in frames:
                (fdir / f"{video.stem}_{t:06.2f}s.jpg").write_bytes(data)

        for m, det in detectors.items():
            stats = Counter()
            times, person_counts = [], Counter()
            for t, data in frames:
                t0 = time.perf_counter()
                res = det.detect(data)
                persons, s = judge(res.detections, det.matching)
                times.append((time.perf_counter() - t0) * 1000)
                person_counts[s["person_count"]] += 1
                stats["violation"] += s["violation"]
                stats["persons"] += len(persons)
                for p in persons:
                    stats[f"helmet_{p['helmet']}"] += 1
                    stats[f"vest_{p['vest']}"] += 1
                row = {"video": video.name, "t": f"{t:.2f}", "model": m, "scenario": scen or "",
                       "person_count": s["person_count"], "violation": s["violation"],
                       "missing_helmet": s["missing_helmet"], "missing_vest": s["missing_vest"],
                       "persons": ";".join(f"{p['helmet']}/{p['vest']}@{p['box']}" for p in persons),
                       "dets": ";".join(f"{d['cls']}:{d['conf']:.2f}" for d in res.detections),
                       "ms": f"{times[-1]:.0f}"}
                if scen:
                    eh, ev, eviol = SCENARIOS[scen]
                    row["violation_ok"] = s["violation"] == eviol
                    stats["violation_ok"] += row["violation_ok"]
                    if eh is None:
                        row["person_ok"] = s["person_count"] == 0
                    else:
                        # 1인 시나리오: 가장 확실한 사람 한 명 기준 (사람 감지 못 하면 오답)
                        top = max(persons, key=lambda p: p["conf"]) if persons else None
                        row["person_ok"] = top is not None
                        row["helmet_ok"] = bool(top and top["helmet"] == eh)
                        row["vest_ok"] = bool(top and top["vest"] == ev)
                        stats["helmet_ok"] += row["helmet_ok"]
                        stats["vest_ok"] += row["vest_ok"]
                    stats["person_ok"] += row["person_ok"]
                rows.append(row)

            n, np_ = len(frames), stats["persons"]
            print(f"  [{m}]  {statistics.mean(times):.0f} ms/frame (median {statistics.median(times):.0f})")
            print(f"    사람 수 분포: {dict(sorted(person_counts.items()))}  위반 판정: {pct(stats['violation'], n)}")
            print(f"    helmet  worn {pct(stats['helmet_worn'], np_)}  missing {pct(stats['helmet_missing'], np_)}"
                  f"  unknown {pct(stats['helmet_unknown'], np_)}   (사람 {np_}명 기준)")
            print(f"    vest    worn {pct(stats['vest_worn'], np_)}  missing {pct(stats['vest_missing'], np_)}"
                  f"  unknown {pct(stats['vest_unknown'], np_)}")
            if scen:
                line = f"    정답률: violation {pct(stats['violation_ok'], n)}  사람감지 {pct(stats['person_ok'], n)}"
                if SCENARIOS[scen][0] is not None:
                    line += f"  helmet {pct(stats['helmet_ok'], n)}  vest {pct(stats['vest_ok'], n)}"
                print(line)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with (args.out / "eval_frames.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"\n프레임별 결과: {args.out / 'eval_frames.csv'}")


if __name__ == "__main__":
    main()
