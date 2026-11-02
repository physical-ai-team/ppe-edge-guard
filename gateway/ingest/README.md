# ingest

ESP32에서 사진을 받아 저장하고 inference에 보낸 뒤, 결과에 따라 SQLite outbox 상태를 바꾸는 서비스다. 담당은 김세광이다.
API 형식은 [docs/interfaces.md ①](../../docs/interfaces.md)을 따른다.

```
POST /api/v1/captures        ESP32 → 사진 수신 (202 / 중복 200)
GET  /api/v1/events/{id}     이벤트 상태·추론 결과 (디버그)
GET  /api/v1/stats           전체 이벤트 통계 (unknown 비율 포함)
GET  /healthz
```

## Docker로 실행 (팀원 노트북 공통)

```powershell
cd gateway
Copy-Item .env.example .env
# .env 수정: DEVICE_TOKEN=dev-token, INFERENCE_MODE=mock
docker compose up --build ingest          # 로그 보며 실행 (Ctrl+C로 종료)
# 다른 터미널:
conda activate ppe-ingest
python scripts/fake_esp32.py --count 5 --wait
curl.exe http://localhost:8000/api/v1/stats
```

데이터(사진 + `gateway.db`)는 named volume `ppe-edge-guard_gateway-data`에 남는다.
지우려면 `docker compose down -v`를 실행한다.

## Docker 없이 실행 (디버깅용)

```powershell
cd gateway/ingest
conda activate ppe-ingest
$env:PYTHONPATH = "..\common"
$env:DEVICE_TOKEN = "dev-token"
$env:DATA_DIR = "..\data"          # gateway/data/ (gitignore 대상)
$env:INFERENCE_MODE = "mock"
uvicorn app.main:create_app --factory --port 8000 --reload
```

## 테스트

```powershell
cd gateway/ingest
conda run -n ppe-ingest python -m pytest -q
```

## 동작 요약

- **수신**
  - 필수 헤더는 엄격하게 검사한다(400/401/413).
  - 선택 헤더(`X-Captured-At`, `X-Trigger`, `X-Detector-Score`)가 잘못되면 무시하고 경고 로그만 남긴다. ESP32는 4xx를 받으면 재시도하지 않으므로, 선택 필드 하나 때문에 위반 사진을 잃지 않기 위해서다.
  - 사진은 fsync 후 저장하고 그다음 202를 응답한다.
- **시계**
  - `X-Captured-At`이 없거나, 파싱할 수 없거나, 수신 시각보다 1시간 넘게 미래이거나, 2024년 이전이면 `captured_at = received_at`, `clock_synced=false`로 기록한다.
- **추론 워커**
  - 이벤트를 한 번에 하나씩 순서대로 처리한다.
  - 일시 오류(연결 실패, 5xx, 잘못된 응답)는 1→2→4…초 간격으로 재시도하며, 간격은 `INFER_MAX_BACKOFF_SEC`를 넘지 않는다. 재시도 횟수 제한은 없다.
  - inference가 400을 반환하거나 사진 파일이 없으면 `infer_failed`로 기록한다.
- **정리** (`CLEANUP_INTERVAL_SEC`마다)
  - 보관 기간이 지났거나 용량 상한을 넘으면 사진을 삭제한다.
  - `received`, `inferring`, `pending_upload`, `upload_failed` 상태의 사진은 지우지 않는다.
  - `upload_failed` 사진이 남아 있으면 건수가 바뀔 때 경고 로그를 남긴다(복구는 [cloud-sync README](../cloud-sync/README.md)).
  - DB 기록은 남긴다(통계용).
