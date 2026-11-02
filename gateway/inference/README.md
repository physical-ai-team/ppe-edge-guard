# inference

JPEG 바이트를 받아 안전모·조끼 착용 여부를 판정하는 무상태 서비스. 계약은 [docs/interfaces.md ②](../../docs/interfaces.md#-ingest--inference).

```
POST /infer   (body: JPEG, 헤더 X-Event-Id 선택) → persons / detections / summary
GET  /healthz → {"status":"ok","model_loaded":true,"model_version":"...","imgsz":640}
```

| 코드 | 경우 |
|---|---|
| 200 | 판정 결과 |
| 400 `invalid_image` | JPEG 아님(`FF D8` 없음), 디코드 실패, 4 MB 초과, 4096×4096 초과 |
| 503 `model_not_loaded` | 모델 파일 없음, classes.yaml 항목 없음, 클래스 이름 불일치 등. `/healthz`의 `detail`에 원인 |

모델 로드에 실패해도 서비스는 뜬다(503 응답, 컨테이너 헬스체크 실패). ingest는 503을 일시 오류로 보고 재시도한다. 모델 파일을 넣고 컨테이너를 재시작하면 된다.

## 구조

| 파일 | 내용 |
|---|---|
| `app/main.py` | FastAPI 앱, `/infer`, `/healthz` |
| `app/model.py` | ONNX 로드, 클래스 이름(ONNX 메타데이터) ↔ `classes.yaml` 대조, JPEG 디코드, 추론 |
| `app/yolo.py` | letterbox·NMS·좌표 복원 (numpy + Pillow). ultralytics와 같은 결과가 나오도록 맞춤 |
| `app/ppe.py` | 사람 박스 ↔ 안전모/조끼 박스 매칭, `persons`·`summary` 생성 |
| `app/config.py` | 환경변수 (`gateway/.env.example`의 inference 항목) |

- **모델 선택:** `MODEL_PATH` 파일명(확장자 제외)이 `model_version`이고, [`../models/classes.yaml`](../models/classes.yaml)의 같은 키 항목을 쓴다.
- **입력 크기:** ONNX 입력 shape를 따른다. `INFER_IMGSZ`와 다르면 경고 로그만 남긴다.
- **리사이즈:** OpenCV `INTER_LINEAR`와 같은 방식(안티앨리어싱 없음)으로 직접 구현했다. Pillow `resize`를 쓰면 검출 결과가 크게 달라진다.
- **EXIF 회전:** 적용하지 않는다. 박스 좌표는 ingest가 기록한 원본 width/height 기준이다.
- **동시 요청:** 요청이 동시에 와도 모델 실행은 한 번에 하나씩 한다(lock). Pi CPU에서 스레드가 과하게 늘지 않게 하기 위해서다.

### 판정 규칙 (`classes.yaml`의 `matching`)

- PPE 박스 면적의 `min_containment`(0.5) 이상이 사람 박스 안에 있고, PPE 박스 중심이 사람 키 기준 세로 구간(`helmet_region` −0.15~0.4, `vest_region` 0.1~0.85) 안에 있으면 그 사람 것으로 본다.
- PPE 박스 하나는 가장 많이 겹치는 사람 한 명에게만 붙는다.
- 한 사람에게 착용·미착용 박스가 같이 붙으면 conf가 높은 쪽을 따른다.
- 아무 박스도 붙지 않으면 `unknown`이다. `unknown`은 위반이 아니다.
- 사람에게 붙지 않은 `no_helmet`/`no_vest`도 위반으로 집계한다.

## 실행

모델 파일 준비 (ppe-training 환경, 처음 한 번):
```powershell
python training/export_hf_model.py       # gateway/models/yolov8n-ppehf-640-v1.onnx (기본값)
python training/export_coco_model.py     # gateway/models/yolov8n-coco-416-v1.onnx (사람만)
```

**conda로 직접 실행** (디버깅이 빠름):
```powershell
cd gateway/inference
$env:MODEL_PATH="../models/yolov8n-ppehf-640-v1.onnx"; $env:MODEL_CLASSES="../models/classes.yaml"; $env:PYTHONPATH=".;../common"
conda run -n ppe-inference --no-capture-output uvicorn app.main:create_app --factory --port 8001
```

**Docker 단독 실행:**
```powershell
cd gateway
docker build -f inference/Dockerfile -t ppe-edge-guard/inference:dev .
docker run --rm -p 8001:8001 -m 1.5g -v "${PWD}/models:/models:ro" ppe-edge-guard/inference:dev
```
> Git Bash에서 실행할 때는 `-e MODEL_PATH=/models/...`가 Windows 경로로 바뀌지 않게 `MSYS_NO_PATHCONV=1`을 붙인다.

**확인:**
```powershell
curl.exe http://localhost:8001/healthz
curl.exe -X POST http://localhost:8001/infer -H "Content-Type: image/jpeg" -H "X-Event-Id: test-1" --data-binary "@<사진>.jpg"
```

## 테스트

```powershell
cd gateway/inference; conda run -n ppe-inference python -m pytest -q
```
- **기본 테스트:** 계약 형식, 판정 규칙(시연 시나리오 5종 포함), 전처리·후처리, 오류 코드를 검사한다.
- **실제 모델 테스트:** `gateway/models/*.onnx`가 있으면 모델마다 실제 로드·계약 검사를 한다. 없으면 skip한다.
- **OpenCV 비교 테스트:** `cv2`가 있는 ppe-training 환경에서만 돈다. inference 환경에서는 skip된다.
- **ultralytics 결과 비교:** `python training/validate_onnx.py <onnx> <사진들> --compare <onnx>`로 확인한다.

## compose 연동 (김세광 님 확인 필요)

`gateway/docker-compose.yml`은 김세광 님 담당이라 이 PR에서 수정하지 않았다. 제안 내용:
```yaml
  inference:
    build:
      context: .
      dockerfile: inference/Dockerfile
    image: ppe-edge-guard/inference:dev
    env_file: .env
    volumes:
      - ./models:/models:ro
    restart: unless-stopped
    mem_limit: 1536m
    healthcheck:
      test: ["CMD", "/opt/conda/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=3)"]
      interval: 30s
      timeout: 5s
      start_period: 30s
      retries: 3
    logging: *default-logging
```
- **포트:** 외부에 열지 않는다. 노트북에서 단독으로 curl할 때만 `docker-compose.dev.yml`에서 `8001:8001`을 연다.
- **모델 마운트:** 모델은 이미지가 아니라 볼륨이므로 bind mount(`./models`)를 쓴다. 읽기 전용이라 SQLite 같은 잠금 문제는 없다.
