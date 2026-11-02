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

- **영상:** 시나리오 4종(`both_worn`, `helmet_only`, `vest_only`, `none_worn`) 1인 영상과 2인 영상(`multi_2p`) 1개. 모두 1280×720, 각 8초, 같은 장소에서 찍었다.
- **프레임:** 초당 4장씩 뽑아 영상당 32장. JPEG 품질 80으로 다시 압축했다(ESP32 사진 조건에 맞춤).
- **판정 기준:** 프레임마다 실제 사람 1명의 판정을 정답과 비교한다. 사람을 검출하지 못한 프레임은 오답으로 센다.
- **실행:** `python training/eval_scenarios.py <영상들> --out <git 밖 폴더>`. 영상과 프레임은 git에 올리지 않는다.

**시나리오별 정답률** (영상당 32프레임)

| 시나리오 | 정답 | 위반 판정 416 / 640 | 안전모 416 / 640 | 조끼 416 / 640 |
|---|---|---|---|---|
| `both_worn` | 위반 아님 | 32 / 32 | 28 / 29 | 27 / 29 |
| `helmet_only` | 위반 (조끼 X) | 32 / 32 | 32 / 32 | 32 / 32 |
| `vest_only` | 위반 (안전모 X) | **0** / **14** | **0** / **14** | 32 / 32 |
| `none_worn` | 위반 (둘 다 X) | 31 / 32 | **9** / **25** | 31 / 31 |
| **합계 (128프레임)** | | **74%** / **86%** | **54%** / **78%** | 95% / 97% |

`both_worn`에서 안전모·조끼가 32가 아닌 건 사람을 검출하지 못한 프레임(416은 4장, 640은 3장) 때문이다. 판정 자체가 틀린 건 아니다.

**안전모 미착용자의 판정 내역** (정답은 모두 `missing`)

| 영상 | 416: missing / worn(오판) / unknown | 640: missing / worn(오판) / unknown |
|---|---|---|
| `vest_only` (32프레임) | 0 / 7 / 25 | 14 / 4 / 14 |
| `none_worn` (32프레임, 사람 미검출 포함) | 9 / 2 / 20 | 25 / 5 / 2 |
| `multi_2p` 오른쪽 사람 (2명 다 잡힌 24프레임) | 0 / 6 / 18 | 13 / 4 / 7 |

| 기타 | 416 | 640 |
|---|---|---|
| 위반 영상 96프레임 중 위반을 놓친 프레임 | 33 (34%) | 18 (19%) |
| 거짓 경보 (`both_worn`을 위반으로, `multi_2p` 왼쪽 착용자를 미착용으로) | 0 | 0 |
| 프레임당 처리 시간 | 약 90 ms | 약 180 ms |

**결과 요약**
- **안전모 착용·조끼:** 두 모델 모두 잘 본다. 안전모 착용은 `both_worn`, `helmet_only`에서 사람만 검출되면 100% 맞았고, 조끼는 95% 이상이다.
- **안전모 미착용:** 차이는 여기서 난다. 416은 대부분 놓쳤고(`vest_only` 0%), 640은 `vest_only` 44%, `none_worn` 78%를 잡았다.
- **640의 남은 문제:**
  - 미착용자를 안전모 `worn`으로 오판하는 경우가 약 15%(13/88) 있다. 위반이 착용으로 둔갑하는 위험한 오류라, T1 학습 모델에서 개선해야 할 첫 항목이다.
  - `vest_only`는 640에서도 절반 이상 놓쳐서 가장 어려운 경우다.
  - `vest_only` 영상 왼쪽 위 구석에서 실제로는 없는 사람이 거의 모든 프레임에 검출된다(conf 0.44–0.69). `unknown`이라 위반 판정에는 영향이 없지만 unknown 통계를 부풀린다.
- **ESP32 연속 촬영 효과:** ESP32는 한 사람을 여러 번 찍어 보내므로, 이벤트 단위로 보면 프레임 단위보다 위반 검출률이 높다.
- **표본 한계:** 장소 1곳, 시나리오당 영상 1개, 서로 비슷한 연속 프레임이라 표본이 적다. 다른 거리·각도·조명으로 추가 촬영하면 같은 명령으로 다시 잰다.
