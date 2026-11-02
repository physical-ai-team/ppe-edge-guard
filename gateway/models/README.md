# gateway/models

inference 컨테이너에 `/models`(읽기 전용)로 마운트되는 폴더. 모델 파일은 **이미지에 굽지 않고 git에도 올리지 않는다** (`*.onnx`, `*.pt`는 gitignore). 팀 공유 드라이브로 배포한다.

파일명 = `model_version` (`{아키텍처}-{데이터}-{입력크기}-v{번호}`, [docs/interfaces.md](../../docs/interfaces.md#모델-버전-이름-model_version))

| 파일 | 설명 |
|---|---|
| `yolov8n-coco-416-v1.onnx` | COCO 사전학습 YOLOv8n, 입력 416. 사람만 감지 (트랙 I1 임시) |
| `yolov8n-ppehf-416-v1.onnx` | 공개 PPE 모델(Hugging Face) export, 입력 416. 아래 참고 |
| `yolov8n-ppehf-640-v1.onnx` | 위와 같은 모델, 입력 640 (비교용) |
| `yolov8n-ppe-416-v1.onnx` | Roboflow Construction Site Safety로 직접 학습, 입력 416 (트랙 T1) |
| `classes.yaml` | 모델별 원본 클래스 이름 → 정규화 5종 매핑. 키 = `model_version` |

I1에서는 COCO 사전학습 모델로 먼저 동작을 확인하고, T1에서 학습한 모델로 교체한다. `.env`의 `MODEL_PATH`만 바꾸면 된다.

## 공개 PPE 모델 (`yolov8n-ppehf-*`)

T1 학습 전에도 실제 안전모·조끼 판정을 해볼 수 있도록 공개 모델을 받아 쓴다.

| 항목 | 값 |
|---|---|
| 출처 | [Hansung-Cho/yolov8-ppe-detection](https://huggingface.co/Hansung-Cho/yolov8-ppe-detection) `best.pt`, 리비전 `ac0027bd38bc` |
| 라이선스 | MIT (데이터셋 라이선스는 원 데이터 제공처를 따름) |
| 구조 | YOLOv8n, 학습 입력 **640**, 30 epochs (ultralytics 8.3.232) |
| 클래스 | 10종. Roboflow "Construction Site Safety"와 이름·순서가 같다 → [interfaces.md 매핑표](../../docs/interfaces.md#원본-클래스--정규화-매핑표) 그대로 적용 |
| 공개 성능 (원 저자 val) | mAP50 0.744, mAP50-95 0.436, P 0.831, R 0.685 |

**생성** (ppe-training 환경):
```powershell
python training/export_hf_model.py               # → yolov8n-ppehf-416-v1.onnx
python training/export_hf_model.py --imgsz 640   # → yolov8n-ppehf-640-v1.onnx
```
스크립트는 리비전·sha256을 고정해서 받고, 체크포인트의 클래스 이름·순서가 `classes.yaml`의 `source_names`와 다르면 실패한다.

**검증**:
```powershell
python training/validate_onnx.py gateway/models/yolov8n-ppehf-416-v1.onnx <사진들.jpg> --compare gateway/models/yolov8n-ppehf-416-v1.onnx
```
numpy + Pillow 전처리(letterbox)·NMS 구현이 ultralytics와 같은 결과를 내는지 비교한다.

> **전처리 주의 (inference 구현 시):** 리사이즈는 OpenCV `INTER_LINEAR`와 같은 bilinear(안티앨리어싱 없음)여야 한다. Pillow `resize(BILINEAR)`는 축소 시 안티앨리어싱을 해서 결과가 크게 달라진다(같은 사진에서 박스 3개 → 10개). `training/validate_onnx.py`의 `resize_bilinear`·`letterbox`를 그대로 가져다 쓴다.

> **입력 크기 주의:** 원 모델은 640으로 학습됐다. 416으로 쓰면 멀리 있는 사람·작은 안전모를 놓치는 경우가 많다. 정확도와 Pi 속도를 보고 416/640 중 결정한다(아래 표).

### 1차 확인 결과 (2026-11-02, 노트북 CPU, 공개 사진 7장)

정규화 클래스만, conf ≥ 0.40.

| 사진 (Wikimedia Commons, 1280px) | 416 | 640 |
|---|---|---|
| `bus.jpg` (ultralytics 샘플) | person 2, no_helmet 1, no_vest 2 | person 2, no_helmet 1 |
| `Construction_worker_CT.jpg` | person 1, helmet 1 | person 1, helmet 1, no_helmet 1 |
| `Hard_Hat_Worker_HHW01.JPG` | person 1, helmet 1, no_vest 1 | person 1, helmet 1, no_vest 1 |
| `Canada_Place_-_workmen_02.jpg` | person 1, vest 1 | person 1, vest 1, helmet 1 |
| `Chinese_construction_workers_in_Israel.jpg` | (없음) | person 2, helmet 2, vest 1 |
| `Construction_workers_at_a_site_on_Södra_Hamngatan,_Gothenburg.jpg` | person 1, vest 1 | person 3, helmet 2, vest 2 |
| `Baliwagenyo_welder_with_green_hard_hat_..._01.jpg` | person 1 | person 1 |
| **추론 시간 (노트북)** | 약 35–60 ms | 약 90–110 ms |

공개 사진이라 시나리오 정답 기준이 아니다. 정확도는 이기태 영상 프레임으로 시나리오별로 다시 잰다. Pi 5 속도는 김세광에게 측정을 요청한다.
