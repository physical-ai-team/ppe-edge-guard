# 서비스 간 인터페이스 계약 (v1.2)

> **상태: 확정 (2026-11-02, 팀 합의).** 이후 변경은 영향받는 담당자 전원의 PR 승인이 필요하다. 계약 변경 PR이 먼저 머지된 뒤 코드 변경을 올린다. 버전 규칙: 필드 추가 = 마이너(v1.1), 필드 삭제·의미 변경 = 메이저(v2.0).

> **최근 변경 — v1.2 (2026-11-02)**: 게이트웨이 로컬 상태에 `upload_failed` 추가. 업로드 영구 오류(429를 제외한 4xx, 사진 파일 없음)가 `SYNC_MAX_PERMANENT_FAILURES`회(기본 5) 쌓이면 재시도를 멈추고, 그 사진은 로컬 정리 대상에서 빠진다. 네트워크·5xx·타임아웃·408·429는 지금처럼 무한 재시도. `/api/v1/events/{id}`에 `sync_attempts`·`sync_error`·`next_sync_at` 추가. **Supabase 스키마·웹·ESP32·inference 형식 변경 없음.** 전체 이력은 [맨 아래](#변경-이력).

이 문서는 담당자들이 **서로의 코드나 라즈베리파이 없이 병렬 개발**할 수 있도록 경계를 고정한다. 구현은 자유지만, 아래 형식은 지켜야 한다.

```
[ESP32]  ──①──▶  [ingest]  ──②──▶  [inference]
 박민성             김세광              김정윤
                     │
                     ▼ (SQLite outbox)
                [cloud-sync] ──③──▶ [Supabase] ──▶ [web]
                  김세광             조아람        조아람
```

## 공통 규칙

| 항목 | 규칙 |
|---|---|
| 시각 | 전송·DB·Storage 경로 모두 **UTC, ISO 8601**, 초 단위 `Z` 접미사. 예: `2026-11-02T05:31:12Z`. **KST 변환은 웹 화면 표시에서만** |
| 시각 종류 | `captured_at` = ESP32 촬영 시각(NTP) / `received_at` = ingest 수신 시각 / `detected_at` = 추론 완료 시각. 세 값은 각각 따로 기록한다 |
| `device_id` | 정규식 `^[a-z0-9-]{3,32}$`. 예: `cam-01`, `cam-minsung` (개발용 개인 장치는 이름 접미사 권장) |
| `event_id` | ingest가 생성. `{device_id}_{YYYYMMDDTHHMMSSZ}_{hex6}` 예: `cam-01_20261102T053112Z_a1b2c3`. 사람이 읽을 수 있고 시간순 정렬됨. 전 구간에서 이 값을 그대로 전달 |
| 박스 좌표 | **원본 이미지 픽셀 좌표**, `[x1, y1, x2, y2]` 정수 (좌상단, 우하단) |
| 이미지 | JPEG만. 바이트가 `FF D8`로 시작해야 함 |

### 정규화 클래스 이름 (canonical classes) — 확정 5종

모델마다 클래스 이름이 다르다(Roboflow는 `NO-Hardhat`, COCO는 `person` 등). 그래서 **inference는 아래 5개 이름으로 정규화해서 응답**한다. 다른 서비스와 웹은 이 5개 이름만 안다.

| canonical | 의미 |
|---|---|
| `person` | 사람 |
| `helmet` | 안전모 착용 |
| `no_helmet` | 안전모 미착용 |
| `vest` | 안전조끼 착용 |
| `no_vest` | 안전조끼 미착용 |

#### 원본 클래스 → 정규화 매핑표

매핑은 **인덱스가 아니라 이름 기준**이다. Roboflow 데이터셋 버전에 따라 인덱스 순서가 달라질 수 있기 때문이다. 실제 인덱스는 export된 `data.yaml`의 `names`로 확인하고, `gateway/models/classes.yaml`(김정윤 관리)에 기록한다.

**Roboflow "Construction Site Safety"** (학습 모델 `yolov8n-ppe-*`)

| 원본 이름 | 참고 인덱스* | → canonical |
|---|---|---|
| `Hardhat` | 0 | `helmet` |
| `Mask` | 1 | (제외) |
| `NO-Hardhat` | 2 | `no_helmet` |
| `NO-Mask` | 3 | (제외) |
| `NO-Safety Vest` | 4 | `no_vest` |
| `Person` | 5 | `person` |
| `Safety Cone` | 6 | (제외) |
| `Safety Vest` | 7 | `vest` |
| `machinery` | 8 | (제외) |
| `vehicle` | 9 | (제외) |

\* 흔히 쓰이는 10클래스 버전 기준이다. 사용한 버전의 `data.yaml`과 다르면 `classes.yaml`을 기준으로 삼는다.

**COCO 사전학습** (I1 단계 임시 모델 `yolov8n-coco-*`)

| 원본 이름 | 인덱스 | → canonical |
|---|---|---|
| `person` | 0 | `person` |
| 나머지 79개 | 1–79 | (제외) |

COCO 모델에는 안전모·조끼 클래스가 없다. 따라서 모든 사람의 `helmet`과 `vest`는 `unknown`이고 `violation`은 항상 `false`다. 위반 경로를 테스트할 때는 ingest `INFERENCE_MODE=mock`을 쓴다.

(제외) 클래스는 응답의 `detections`에 넣지 않는다.

### 모델 버전 이름 (`model_version`)

형식: `{아키텍처}-{데이터}-{입력크기}-v{번호}` — 소문자, 하이픈 구분

| 예 | 의미 |
|---|---|
| `yolov8n-ppe-416-v1` | Roboflow PPE로 학습한 첫 모델, 입력 416 |
| `yolov8n-ppe-416-v2` | 재학습·데이터 추가 등으로 갱신된 모델 |
| `yolov8n-coco-416-v1` | COCO 사전학습 모델 (임시) |

- ONNX 파일명은 버전과 같게 짓는다: `gateway/models/{model_version}.onnx`
- `classes.yaml`의 `model_version` 값이 응답의 `model_version`이 된다.

---

## ① ESP32 → ingest

### `POST /api/v1/captures`

| 항목 | 값 |
|---|---|
| URL | `http://{GATEWAY_HOST}:{GATEWAY_PORT}/api/v1/captures` (기본 포트 `8000`) |
| Body | **JPEG 원본 바이트 그대로** (multipart 아님 — ESP32 `HTTPClient.POST(buf, len)`로 바로 전송) |
| 최대 크기 | 2 MB |
| 해상도 | **계약으로 고정하지 않는다.** 펌웨어 설정값으로 뺀다(`config.h`의 `CAPTURE_FRAMESIZE`, `CAPTURE_JPEG_QUALITY`) |
| 기본값 | SXGA 1280×1024, JPEG quality 10~12 (esp32-camera 기준, 낮을수록 고화질). 전송 시간을 측정한 뒤 박민성이 조정한다 |
| ingest 검증 | 2 MB 이하의 유효한 JPEG이면 해상도와 관계없이 받는다. 해상도는 로그와 이벤트 기록에만 남긴다 |

**헤더**

| 헤더 | 필수 | 설명 | 예 |
|---|---|---|---|
| `Content-Type` | ✅ | 고정 | `image/jpeg` |
| `X-Device-Id` | ✅ | 위 `device_id` 규칙 | `cam-01` |
| `X-Device-Token` | ✅ | 공유 토큰. ESP32 `secrets.h`의 `DEVICE_TOKEN` = 게이트웨이 `.env`의 `DEVICE_TOKEN` | `9f3c...` |
| `X-Capture-Id` | ✅ | 장치가 만든 촬영 고유 ID. **재시도 시 같은 값 유지** → ingest가 중복 제거. 형식 자유(최대 64자), 권장 `{부팅시 랜덤 hex8}-{순번}` | `5e1a9c02-000042` |
| `X-Captured-At` | ⬜* | 촬영 시각(UTC ISO 8601)이다. 펌웨어는 **NTP를 사용**한다(`configTime(0, 0, "pool.ntp.org", ...)`). 동기화되지 않았으면 이 헤더를 **생략**한다. 잘못된 시각은 보내지 않는다 | `2026-11-02T05:31:12Z` |
| `X-Trigger` | ⬜ | 촬영 계기: `person` / `timer` / `serial` / `manual` | `person` |
| `X-Detector-Score` | ⬜ | Edge Impulse 사람 감지 점수 0~1 | `0.87` |
| `X-Firmware-Version` | ⬜ | 디버깅용 | `0.1.0` |

\* NTP가 정상이면 항상 보낸다. 헤더가 없을 때만 선택으로 취급한다.

**ingest의 시각 기록 규칙**
- ingest는 요청을 받은 시각을 **항상 `received_at`으로 따로 기록**한다.
- `captured_at`에는 `X-Captured-At` 값을 쓴다. 헤더가 없으면 `received_at` 값을 쓰고 `clock_synced = false`로 표시한다.
- 다음 경우는 장치 시계 오류로 보고, 헤더가 없을 때와 같이 처리한다(`clock_synced = false`, 경고 로그). 이 때문에 요청을 거부하지는 않는다.
  - `X-Captured-At`이 `received_at`보다 1시간 이상 미래
  - `X-Captured-At`이 `2024-01-01T00:00:00Z` 이전 (NTP 동기화 전의 1970년 시각 등)
  - 파싱할 수 없는 값

**선택 헤더 처리 원칙**: ESP32는 4xx를 받으면 재시도하지 않는다. 그래서 선택 헤더(`X-Captured-At`, `X-Trigger`, `X-Detector-Score`, `X-Firmware-Version`)의 값이 잘못돼도 400을 돌려주지 않는다. 그 값만 무시하고 경고 로그를 남긴다. 사진을 잃지 않기 위해서다.

**예시 요청 (PowerShell / curl)**
```powershell
curl.exe -X POST http://localhost:8000/api/v1/captures `
  -H "Content-Type: image/jpeg" `
  -H "X-Device-Id: cam-01" `
  -H "X-Device-Token: dev-token" `
  -H "X-Capture-Id: 5e1a9c02-000042" `
  -H "X-Captured-At: 2026-11-02T05:31:12Z" `
  -H "X-Trigger: serial" `
  --data-binary "@sample.jpg"
```

**응답**

| 코드 | 의미 | ESP32 동작 |
|---|---|---|
| `202` | 저장 완료, 추론 대기열 등록 | 성공 → 쿨다운 시작 |
| `200` | 같은 `X-Capture-Id`가 이미 처리됨 (중복) | 성공으로 취급 |
| `400` | JPEG 아님 / 필수 헤더 누락 / 형식 오류 | **재시도 금지**, 시리얼에 에러 출력 |
| `401` | 토큰 불일치 | **재시도 금지** |
| `413` | 2 MB 초과 | **재시도 금지** (해상도/품질 낮추기) |
| `503` | 일시적 불가 (디스크 가득 등). `Retry-After` 헤더(초) 포함 | 재시도 |
| 네트워크 오류 / 타임아웃 | — | 재시도 (최대 3회, 1s → 2s → 4s 백오프, 타임아웃 10s) |

```json
// 202 Accepted
{ "event_id": "cam-01_20261102T053112Z_a1b2c3", "status": "received" }

// 200 OK (중복)
{ "event_id": "cam-01_20261102T053112Z_a1b2c3", "status": "duplicate" }

// 4xx/5xx 공통 형식
{ "error": "invalid_token", "detail": "X-Device-Token mismatch" }
```
`error` 값: `missing_header`, `invalid_header`, `invalid_image`, `invalid_token`, `payload_too_large`, `unavailable`

### `GET /healthz`
```json
{ "status": "ok", "inference_mode": "mock" }
```
`inference_mode`: `http`(실제 inference 호출) | `mock`(가짜 결과). 지금 어느 모드로 떠 있는지 확인하는 용도다.

### `GET /api/v1/events/{event_id}` (디버그용)
```json
{
  "event_id": "cam-01_20261102T053112Z_a1b2c3",
  "device_id": "cam-01",
  "capture_id": "5e1a9c02-000042",
  "status": "pending_upload",
  "captured_at": "2026-11-02T05:31:12Z",
  "received_at": "2026-11-02T05:31:13Z",
  "clock_synced": true,
  "detected_at": "2026-11-02T05:31:13Z",
  "trigger": "serial",
  "image": { "width": 1280, "height": 1024, "bytes": 184322, "deleted": false },
  "infer_attempts": 1,
  "last_error": null,
  "sync_attempts": 1,
  "sync_error": "storage: 503 Service Unavailable",
  "next_sync_at": "2026-11-02T05:31:15Z",
  "uploaded_at": null,
  "result": { "...": "② inference 응답 전체 (추론 전이면 null)" }
}
```
- `status`: `received` → `inferring` → `compliant` | `pending_upload` → `uploaded` | `upload_failed`
  - 추론 일시 오류: `received`로 돌아가서 재시도한다.
  - 추론 영구 오류(손상 이미지, 파일 없음): `infer_failed`
  - 업로드 일시 오류(연결 실패, 타임아웃, 5xx, 408, 429): `pending_upload`를 유지하고 백오프로 **무한 재시도**한다.
  - 업로드 영구 오류(429·408을 제외한 4xx, 사진 파일 없음): `SYNC_MAX_PERMANENT_FAILURES`회(기본 5) 쌓이면 `upload_failed`로 바꾸고 재시도를 멈춘다. 일시 오류 횟수는 이 한도에 세지 않는다.
  - `upload_failed` 사진은 **로컬 정리(보관 기간·용량 상한) 대상에서 제외**하고 경고 로그를 남긴다. 원인을 고친 뒤 `docker compose exec cloud-sync python -m app.requeue [event_id]`로 `pending_upload`에 되돌린다.
- `image.deleted`: 로컬 사진이 정리되었는지. 착용자 사진 즉시 삭제, 보관 기간 경과, 용량 상한 초과로 정리된다. 기록은 남는다.
- `infer_attempts` / `last_error`: inference 호출 횟수와 마지막 오류 메시지(성공하면 `null`)
- `sync_attempts` / `sync_error` / `next_sync_at`: 업로드 시도 횟수(일시·영구 합계), 마지막 업로드 오류(성공하면 `null`), 다음 재시도 예정 시각(대기 중이 아니면 `null`)
- 없는 ID: `404 {"error": "not_found", "detail": "..."}`

`GET /api/v1/stats`의 `since`가 ISO 8601 형식이 아니면 `400 {"error": "invalid_query", "detail": "..."}`를 반환한다(형식은 아래 "unknown 통계" 참고).

---

## ② ingest → inference

### `POST /infer`

inference는 **무상태**다. 공유 볼륨의 파일 경로가 아니라 **이미지 바이트를 직접 받는다** → inference 컨테이너를 노트북에서 단독으로 띄우고 curl로 바로 테스트 가능.

| 항목 | 값 |
|---|---|
| URL | `http://inference:8001/infer` (compose 내부망. 단독 실행 시 `http://localhost:8001/infer`) |
| Body | JPEG 원본 바이트 |
| 헤더 | `Content-Type: image/jpeg` (필수), `X-Event-Id` (선택, 로그 연동용) |
| 타임아웃 | ingest 측 15s. 실패 시 ingest가 백오프 재시도 |

```powershell
curl.exe -X POST http://localhost:8001/infer -H "Content-Type: image/jpeg" --data-binary "@sample.jpg"
```

**응답 `200`**
```json
{
  "event_id": "cam-01_20261102T053112Z_a1b2c3",
  "model_version": "yolov8n-ppe-416-v1",
  "image": { "width": 1280, "height": 1024 },
  "inference_ms": 142.7,
  "persons": [
    {
      "box": [412, 180, 655, 940],
      "conf": 0.91,
      "helmet": "missing",
      "vest": "worn"
    },
    {
      "box": [820, 210, 1010, 900],
      "conf": 0.84,
      "helmet": "worn",
      "vest": "unknown"
    }
  ],
  "detections": [
    { "cls": "person",    "conf": 0.91, "box": [412, 180, 655, 940] },
    { "cls": "no_helmet", "conf": 0.77, "box": [470, 180, 590, 290] },
    { "cls": "vest",      "conf": 0.81, "box": [440, 380, 640, 640] },
    { "cls": "person",    "conf": 0.84, "box": [820, 210, 1010, 900] },
    { "cls": "helmet",    "conf": 0.88, "box": [860, 205, 960, 290] }
  ],
  "summary": {
    "person_count": 2,
    "missing_helmet": true,
    "missing_vest": false,
    "violation": true,
    "unknown_helmet_count": 0,
    "unknown_vest_count": 1
  }
}
```

**필드 규칙**
- `persons[].helmet` / `vest`: `"worn"` | `"missing"` | `"unknown"`
  - `missing`: `no_helmet`/`no_vest` 검출이 해당 사람 박스에 매칭됨
  - `worn`: `helmet`/`vest` 검출이 매칭됨
  - `unknown`: 둘 다 없음 (가려짐, 뒷모습, 사람 감지만 되는 모델 등)
  - 매칭 방식(영역·IoU 기준)은 inference 내부 구현 — `classes.yaml`로 조정
- `summary.missing_helmet` = 어떤 사람이라도 `helmet == "missing"`. `missing_vest`도 동일
- **사람 박스와 매칭되지 않은 `no_helmet`/`no_vest` 검출도 위반으로 집계** (사람 박스가 놓친 경우 대비)
- `summary.violation` = `missing_helmet || missing_vest`. **`unknown`은 위반이 아니다.**
- `summary.unknown_helmet_count` / `unknown_vest_count`: `helmet`/`vest`가 `"unknown"`인 사람 수. 위반 판정에는 쓰지 않고 **통계용으로만 기록**한다(아래 "unknown 통계" 참고).
- `person_count == 0`이고 `no_*` 검출도 없으면 `violation: false`
- `detections`: 정규화 클래스만, `conf` 내림차순 정렬 불필요
- **추가 필드 허용**: 응답을 받는 쪽은 모르는 필드를 무시한다. 예를 들어 ingest의 `INFERENCE_MODE=mock` 응답에는 `"mock_scenario": "helmet_only"`와 `"model_version": "mock-ppe-416-v1"`이 들어간다. 실제 inference는 이 필드를 보낼 필요가 없다.

**오류**
| 코드 | 의미 |
|---|---|
| `400` | `{"error": "invalid_image"}` — 디코드 실패 |
| `503` | `{"error": "model_not_loaded"}` — 모델 파일 없음/로드 실패 |

### `GET /healthz`
```json
{ "status": "ok", "model_loaded": true, "model_version": "yolov8n-ppe-416-v1", "imgsz": 416 }
```
모델이 없으면 `503` + `"model_loaded": false` (컨테이너 헬스체크 실패로 표시됨).

### 시연 시나리오별 기대 출력 (1인 촬영 기준)

이기태 담당 검증·시연 영상의 5개 분류와 기대 결과. inference 정확도 측정과 통합 테스트의 정답 기준으로 사용한다.

| 시나리오 ID | 상황 | `helmet` | `vest` | `violation` | Supabase 기록 |
|---|---|---|---|---|---|
| `both_worn` | 둘 다 착용 | worn | worn | false | 없음 |
| `helmet_only` | 안전모만 | worn | missing | **true** | 있음 (조끼 미착용) |
| `vest_only` | 조끼만 | missing | worn | **true** | 있음 (안전모 미착용) |
| `none_worn` | 둘 다 미착용 | missing | missing | **true** | 있음 (둘 다) |
| `no_person` | 사람 없음 | — | — | false (`person_count: 0`) | 없음 |

### unknown 통계

`unknown`은 위반이 아니지만 비율이 높으면 모델이나 카메라 각도에 문제가 있다는 신호다. 그래서 두 곳에 기록한다.

| 위치 | 범위 | 용도 |
|---|---|---|
| ingest 로컬 SQLite `events` | **모든 이벤트** (착용·위반·사람 없음 포함). 사진은 지워도 이 기록은 남긴다 | `GET /api/v1/stats` 로 조회. 모델·카메라 점검용 |
| Supabase `violations` | 위반 건만 | 위반 사진 중 판단 불가 비율 확인 (웹 통계) |

**`GET /api/v1/stats?since=2026-11-01T00:00:00Z&device_id=cam-01`** (ingest. 파라미터는 모두 선택)
```json
{
  "since": "2026-11-01T00:00:00Z",
  "device_id": "cam-01",
  "events": 412,
  "by_status": { "compliant": 350, "pending_upload": 2, "uploaded": 54, "upload_failed": 1, "infer_failed": 5 },
  "persons": 498,
  "violations": 57,
  "unknown_helmet_count": 31,
  "unknown_vest_count": 64,
  "unknown_helmet_rate": 0.062,
  "unknown_vest_rate": 0.129,
  "by_model_version": { "yolov8n-ppe-416-v1": 412 }
}
```
`*_rate` = unknown 수 / `persons` (`persons`가 0이면 0)

---

## ③ cloud-sync → Supabase (web이 읽는 형식)

### Storage

| 항목 | 값 |
|---|---|
| 버킷 | `violation-images` (**private**) |
| 경로 | `{device_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg` — 날짜는 `captured_at`의 UTC 기준 |
| 예 | `cam-01/2026/11/02/cam-01_20261102T053112Z_a1b2c3.jpg` |
| 업로드 | `upsert: true`, `contentType: image/jpeg` (재시도 시 덮어쓰기 = 멱등) |
| 웹 조회 | `supabase.storage.from('violation-images').createSignedUrl(image_path, 3600)` |

### 테이블 `public.violations`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | `uuid` | PK, default `gen_random_uuid()` | |
| `event_id` | `text` | **NOT NULL UNIQUE** | 게이트웨이 생성 ID. cloud-sync는 이 컬럼으로 upsert |
| `device_id` | `text` | NOT NULL | |
| `captured_at` | `timestamptz` | NOT NULL | 촬영 시각 (UTC). ESP32 시계가 동기화되지 않았으면 `received_at`과 같은 값 |
| `received_at` | `timestamptz` | NOT NULL | ingest 수신 시각 (UTC) |
| `clock_synced` | `boolean` | NOT NULL | `captured_at`이 ESP32 NTP 시각이면 true |
| `detected_at` | `timestamptz` | NOT NULL | 추론 완료 시각 (UTC) |
| `image_path` | `text` | NOT NULL | Storage 버킷 내 경로 (버킷명 제외) |
| `missing_helmet` | `boolean` | NOT NULL | `summary.missing_helmet` |
| `missing_vest` | `boolean` | NOT NULL | `summary.missing_vest` |
| `person_count` | `int` | NOT NULL | `summary.person_count` |
| `unknown_helmet_count` | `int` | NOT NULL default 0 | `summary.unknown_helmet_count` (통계용) |
| `unknown_vest_count` | `int` | NOT NULL default 0 | `summary.unknown_vest_count` (통계용) |
| `persons` | `jsonb` | NOT NULL default `'[]'` | ② 응답의 `persons` 배열 그대로 (웹에서 박스 오버레이용) |
| `model_version` | `text` | | |
| `inference_ms` | `real` | | |
| `created_at` | `timestamptz` | NOT NULL default `now()` | Supabase 삽입 시각 |

인덱스: `captured_at desc`, `device_id`.
권한: RLS on, `authenticated`에 `select`만 허용. 쓰기는 service_role(cloud-sync)만.
Realtime: `supabase_realtime` publication에 포함 → 웹은 `INSERT` 이벤트 구독.

**cloud-sync가 보내는 upsert 예시**
```json
{
  "event_id": "cam-01_20261102T053112Z_a1b2c3",
  "device_id": "cam-01",
  "captured_at": "2026-11-02T05:31:12Z",
  "received_at": "2026-11-02T05:31:13Z",
  "clock_synced": true,
  "detected_at": "2026-11-02T05:31:13Z",
  "image_path": "cam-01/2026/11/02/cam-01_20261102T053112Z_a1b2c3.jpg",
  "missing_helmet": true,
  "missing_vest": false,
  "person_count": 2,
  "unknown_helmet_count": 0,
  "unknown_vest_count": 1,
  "persons": [
    { "box": [412, 180, 655, 940], "conf": 0.91, "helmet": "missing", "vest": "worn" },
    { "box": [820, 210, 1010, 900], "conf": 0.84, "helmet": "worn", "vest": "unknown" }
  ],
  "model_version": "yolov8n-ppe-416-v1",
  "inference_ms": 142.7
}
```
웹은 `captured_at`을 KST(`Asia/Seoul`)로 변환해서 표시한다. DB와 Storage 경로는 UTC 그대로 둔다.
upsert 키: `on_conflict=event_id`. 순서: **Storage 업로드 성공 → 테이블 upsert** (웹이 사진 없는 행을 보지 않도록).

---

## 확정 내역 (2026-11-02 팀 합의)

| # | 항목 | 담당 | 결정 |
|---|---|---|---|
| 1 | ESP32 전송 형식 | 박민성, 김세광 | raw JPEG body (multipart 아님) |
| 2 | 촬영 해상도 | 박민성 | SXGA로 시작. 펌웨어 설정값(`CAPTURE_FRAMESIZE`)으로 빼고 전송 시간 측정 후 조정 |
| 3 | 촬영 시각 | 박민성, 김세광 | ESP32는 NTP 사용. ingest는 `received_at`을 별도 기록하고 `clock_synced` 플래그를 남김 |
| 4 | 클래스 | 김정윤 | 정규화 5종 `person` `helmet` `no_helmet` `vest` `no_vest`. Roboflow·COCO 매핑표 추가 |
| 5 | `unknown` | 김정윤 | 위반 아님. `unknown_helmet_count` / `unknown_vest_count`를 기록해 통계로 조회 |
| 6 | 모델 버전 이름 | 김정윤 | `yolov8n-ppe-416-v1` 형식, ONNX 파일명과 동일 |
| 7 | `persons` 저장 | 조아람 | Supabase `jsonb` 컬럼 |
| 8 | 시각 기준 | 조아람 | Storage 경로와 DB는 UTC, 웹 표시만 KST |

## 변경 이력
| 버전 | 날짜 | 내용 |
|---|---|---|
| v0.1 | 2026-11-02 | 초안 |
| v1.0 | 2026-11-02 | 팀 확정. `received_at`·`clock_synced` 추가, 해상도를 펌웨어 설정으로 이동, 클래스 매핑표, `unknown_*_count` + `GET /api/v1/stats`, 모델 버전 이름 `yolov8n-ppe-416-v1` |
| v1.1 | 2026-11-02 | ingest 구현(G1)에 맞춰 디버그용 필드 추가: `/healthz`의 `inference_mode`, `/api/v1/events/{id}`의 `capture_id`·`detected_at`·`trigger`·`image.deleted`·`infer_attempts`·`last_error`·`uploaded_at`, 404 `not_found`, stats의 400 `invalid_query`. 2024년 이전 `X-Captured-At`도 시계 오류로 처리. 선택 헤더가 잘못돼도 무시만 하고 거부하지 않는 원칙 명시. inference 응답의 추가 필드 허용(mock의 `mock_scenario`). **기존 필드 변경 없음** |
| v1.2 | 2026-11-02 | 업로드 오류 분류: 연결 실패·타임아웃·5xx·408·429는 무한 재시도, 그 밖의 4xx·사진 파일 없음은 영구 오류로 `SYNC_MAX_PERMANENT_FAILURES`회(기본 5) 후 새 상태 `upload_failed`(재시도 중단, 로컬 정리 제외, 경고 로그, `app.requeue`로 수동 복구). `/api/v1/events/{id}`에 `sync_attempts`·`sync_error`·`next_sync_at` 추가. **기존 필드 변경 없음, Supabase·웹·ESP32·inference 영향 없음** |
