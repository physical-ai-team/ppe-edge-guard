# gateway/models

inference 컨테이너에 `/models`(읽기 전용)로 마운트되는 폴더. 모델 파일은 **이미지에 굽지 않고 git에도 올리지 않는다** (`*.onnx`, `*.pt`는 gitignore). 팀 공유 드라이브로 배포한다.

파일명 = `model_version` (`{아키텍처}-{데이터}-{입력크기}-v{번호}`, [docs/interfaces.md](../../docs/interfaces.md#모델-버전-이름-model_version))

| 파일 | 설명 |
|---|---|
| `yolov8n-coco-416-v1.onnx` | COCO 사전학습 YOLOv8n, 입력 416. 사람만 감지. `python training/export_coco_model.py` |
| `yolov8n-ppehf-640-v1.onnx` | 공개 PPE 모델(Hugging Face) export, 입력 640. **현재 `.env.example` 기본값.** 아래 참고 |
| `yolov8n-ppehf-416-v1.onnx` | 위와 같은 모델, 입력 416 (비교용) |
| `yolov8n-ppe-640-v1.onnx` | Roboflow Construction Site Safety로 직접 학습, 입력 640 (트랙 T1) |
| `classes.yaml` | 모델별 원본 클래스 이름 → 정규화 5종 매핑 + 사람별 판정 규칙(`matching`). 키 = `model_version` |

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
python training/export_hf_model.py               # → yolov8n-ppehf-640-v1.onnx (기본값)
python training/export_hf_model.py --imgsz 416   # → yolov8n-ppehf-416-v1.onnx (비교용)
```
스크립트는 리비전·sha256을 고정해서 받고, 체크포인트의 클래스 이름·순서가 `classes.yaml`의 `source_names`와 다르면 실패한다.

**검증**:
```powershell
python training/validate_onnx.py gateway/models/yolov8n-ppehf-640-v1.onnx <사진들.jpg> --compare gateway/models/yolov8n-ppehf-640-v1.onnx
```
inference 서비스 코드(`gateway/inference/app`)로 실행해서 사람별 판정까지 출력하고, ultralytics와 같은 검출 결과가 나오는지 비교한다.

> **전처리 주의 (inference 구현 시):** 리사이즈는 OpenCV `INTER_LINEAR`와 같은 bilinear(안티앨리어싱 없음)여야 한다. Pillow `resize(BILINEAR)`는 축소 시 안티앨리어싱을 해서 결과가 크게 달라진다(같은 사진에서 박스 3개 → 10개). 구현은 `gateway/inference/app/yolo.py`에 있다.

> **입력 크기: 640으로 결정 (2026-11-02).** 원 모델은 640으로 학습됐다. 416으로 쓰면 안전모 미착용을 거의 잡지 못한다(아래 "시나리오 영상 평가"). Pi 5 속도는 김세광이 측정해서 확인한다.

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

### 시나리오 영상 평가 — 416 vs 640 (2026-11-02, 노트북 CPU)

- **평가 대상:** 안전모 판정만 본다. 이 영상들은 안전모를 확인하려고 찍었다.
- **영상:** 1280×720, 각 8초.
- **프레임:** 초당 4장씩 뽑아 영상당 32장. JPEG 품질 80으로 다시 압축했다(ESP32 사진 조건에 맞춤).
- **실행:** `python training/eval_scenarios.py <영상> --out <git 밖 폴더>`

| 안전모 판정 | 416 | 640 |
|---|---|---|
| `vest_only_lab_01`: 미착용자를 `missing`으로 (정답) | **0** / 32 | **14** / 32 |
| 　〃 `worn`으로 오판 / `unknown` | 7 / 25 | 4 / 14 |
| `multi_2p_lab_01`: 오른쪽 미착용자를 `missing`으로 (정답, 2명 다 잡힌 프레임 기준) | **0** / 24 | **13** / 24 |
| 　〃 `worn`으로 오판 / `unknown` | 6 / 18 | 4 / 7 |
| `multi_2p_lab_01`: 왼쪽 착용자를 `worn`으로 (정답) | 24 / 24 | 24 / 24 |
| 착용자를 미착용으로 오판 (거짓 경보) | 0 | 0 |
| 프레임당 처리 시간 | 약 150 ms | 약 300 ms |

**결과 요약**
- **416:** 미착용자를 한 번도 `missing`으로 판정하지 못했다. 위반 기록이 전혀 남지 않는다.
- **640:** 미착용자를 프레임의 약 절반에서 잡는다. ESP32는 한 사람을 여러 번 찍어 보내므로 이벤트 단위로는 더 높아진다.
- **남은 문제:**
  - 640에서도 미착용자를 `worn`으로 판정하는 경우가 약 15%(8/56) 있다. T1 학습 모델에서 개선해야 할 항목이다.
  - `vest_only` 영상 왼쪽 위 구석에서, 실제로는 없는 사람이 거의 모든 프레임에 검출된다(conf 0.44–0.69). `unknown`이라 위반 판정에는 영향이 없지만 unknown 통계를 부풀린다.
- **표본 한계:** 영상 2개, 장소 1곳, 서로 비슷한 연속 프레임이라 표본이 적다. 시나리오 5종을 다른 거리·각도로 추가 촬영하면 같은 명령으로 다시 잰다.
