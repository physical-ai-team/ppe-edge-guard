# 서비스 간 인터페이스 계약 (v0.1 초안)

> **상태: 초안 — 팀 확인 전.** 아래 "확정 필요 사항"에 대해 담당자들이 합의하면 v1.0으로 올리고, 그 이후 변경은 영향받는 담당자 전원의 PR 승인이 필요하다.

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
| 시각 | 항상 **UTC, ISO 8601**, 초 단위 `Z` 접미사. 예: `2026-11-02T05:31:12Z`. 표시용 KST 변환은 웹에서만 |
| `device_id` | 정규식 `^[a-z0-9-]{3,32}$`. 예: `cam-01`, `cam-minsung` (개발용 개인 장치는 이름 접미사 권장) |
| `event_id` | ingest가 생성. `{device_id}_{YYYYMMDDTHHMMSSZ}_{hex6}` 예: `cam-01_20261102T053112Z_a1b2c3`. 사람이 읽을 수 있고 시간순 정렬됨. 전 구간에서 이 값을 그대로 전달 |
| 박스 좌표 | **원본 이미지 픽셀 좌표**, `[x1, y1, x2, y2]` 정수 (좌상단, 우하단) |
| 이미지 | JPEG만. 바이트가 `FF D8`로 시작해야 함 |

### 정규화 클래스 이름 (canonical classes)

모델마다 클래스 이름이 다르므로(Roboflow는 `NO-Hardhat`, COCO는 `person` 등) **inference가 아래 5개 이름으로 정규화해서 응답**한다. 모델별 매핑은 `gateway/models/classes.yaml`(김정윤 관리)에 둔다.

| canonical | 의미 | Roboflow "Construction Site Safety" 원본 이름 |
|---|---|---|
| `person` | 사람 | `Person` |
| `helmet` | 안전모 착용 | `Hardhat` |
| `no_helmet` | 안전모 미착용 | `NO-Hardhat` |
| `vest` | 조끼 착용 | `Safety Vest` |
| `no_vest` | 조끼 미착용 | `NO-Safety Vest` |

그 외 클래스(`Mask`, `NO-Mask`, `Safety Cone`, `machinery`, `vehicle` 등)는 응답에서 **제외**한다.

---

## ① ESP32 → ingest

### `POST /api/v1/captures`

| 항목 | 값 |
|---|---|
| URL | `http://{GATEWAY_HOST}:{GATEWAY_PORT}/api/v1/captures` (기본 포트 `8000`) |
| Body | **JPEG 원본 바이트 그대로** (multipart 아님 — ESP32 `HTTPClient.POST(buf, len)`로 바로 전송) |
| 최대 크기 | 2 MB |
| 권장 해상도 | SXGA 1280×1024 (최소 640×480). JPEG quality 10~12 (esp32-camera 기준, 낮을수록 고화질) |

**헤더**

| 헤더 | 필수 | 설명 | 예 |
|---|---|---|---|
| `Content-Type` | ✅ | 고정 | `image/jpeg` |
| `X-Device-Id` | ✅ | 위 `device_id` 규칙 | `cam-01` |
| `X-Device-Token` | ✅ | 공유 토큰. ESP32 `secrets.h`의 `DEVICE_TOKEN` = 게이트웨이 `.env`의 `DEVICE_TOKEN` | `9f3c...` |
| `X-Capture-Id` | ✅ | 장치가 만든 촬영 고유 ID. **재시도 시 같은 값 유지** → ingest가 중복 제거. 형식 자유(최대 64자), 권장 `{부팅시 랜덤 hex8}-{순번}` | `5e1a9c02-000042` |
| `X-Captured-At` | ⬜ | 촬영 시각 UTC ISO 8601. NTP 미동기화면 **생략** → ingest 수신 시각 사용 | `2026-11-02T05:31:12Z` |
| `X-Trigger` | ⬜ | 촬영 계기: `person` / `timer` / `serial` / `manual` | `person` |
| `X-Detector-Score` | ⬜ | Edge Impulse 사람 감지 점수 0~1 | `0.87` |
| `X-Firmware-Version` | ⬜ | 디버깅용 | `0.1.0` |

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

### `GET /healthz` → `200 {"status": "ok"}`
### `GET /api/v1/events/{event_id}` (디버그용)
```json
{
  "event_id": "cam-01_20261102T053112Z_a1b2c3",
  "device_id": "cam-01",
  "status": "pending_upload",
  "captured_at": "2026-11-02T05:31:12Z",
  "received_at": "2026-11-02T05:31:13Z",
  "result": { "...": "② inference 응답 전체" }
}
```
`status`: `received` → `inferring` → `compliant` | `pending_upload` → `uploaded` (실패 시 `infer_failed` / 재시도)

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
  "model_version": "ppe_yolov8n_416_v1",
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
    "violation": true
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
- `summary.violation` = `missing_helmet || missing_vest`. **`unknown`은 위반 아님**
- `person_count == 0`이고 `no_*` 검출도 없으면 `violation: false`
- `detections`: 정규화 클래스만, `conf` 내림차순 정렬 불필요

**오류**
| 코드 | 의미 |
|---|---|
| `400` | `{"error": "invalid_image"}` — 디코드 실패 |
| `503` | `{"error": "model_not_loaded"}` — 모델 파일 없음/로드 실패 |

### `GET /healthz`
```json
{ "status": "ok", "model_loaded": true, "model_version": "ppe_yolov8n_416_v1", "imgsz": 416 }
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
| `captured_at` | `timestamptz` | NOT NULL | 촬영 시각 (ESP32 미동기화 시 ingest 수신 시각) |
| `detected_at` | `timestamptz` | NOT NULL | 추론 완료 시각 |
| `image_path` | `text` | NOT NULL | Storage 버킷 내 경로 (버킷명 제외) |
| `missing_helmet` | `boolean` | NOT NULL | `summary.missing_helmet` |
| `missing_vest` | `boolean` | NOT NULL | `summary.missing_vest` |
| `person_count` | `int` | NOT NULL | `summary.person_count` |
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
  "detected_at": "2026-11-02T05:31:13Z",
  "image_path": "cam-01/2026/11/02/cam-01_20261102T053112Z_a1b2c3.jpg",
  "missing_helmet": true,
  "missing_vest": false,
  "person_count": 2,
  "persons": [
    { "box": [412, 180, 655, 940], "conf": 0.91, "helmet": "missing", "vest": "worn" },
    { "box": [820, 210, 1010, 900], "conf": 0.84, "helmet": "worn", "vest": "unknown" }
  ],
  "model_version": "ppe_yolov8n_416_v1",
  "inference_ms": 142.7
}
```
upsert 키: `on_conflict=event_id`. 순서: **Storage 업로드 성공 → 테이블 upsert** (웹이 사진 없는 행을 보지 않도록).

---

## 확정 필요 사항 (팀 회의 안건)

| # | 질문 | 관련 | 초안 제안 |
|---|---|---|---|
| 1 | ESP32 전송을 raw JPEG body로 할지 multipart로 할지 | 박민성, 김세광 | raw (ESP32 구현 단순, 메모리 복사 없음) |
| 2 | 권장 해상도 SXGA가 XIAO PSRAM/전송 시간에 무리 없는지 | 박민성 | 실측 후 SVGA(800×600)로 낮출 수 있음 |
| 3 | `X-Captured-At` — ESP32에서 NTP 동기화 넣을지 | 박민성 | 넣음 (`configTime`), 실패 시 헤더 생략 |
| 4 | 정규화 클래스 5종과 `unknown`은 위반 아님 규칙 | 김정윤, 조아람 | 위 표대로 |
| 5 | `persons` JSON을 Supabase에 저장해 웹에서 박스 오버레이 할지 | 조아람 | 저장 (오버레이는 선택 구현) |
| 6 | Storage 경로 날짜 기준 UTC | 조아람 | UTC (표시만 KST) |
| 7 | `model_version` 명명 규칙 | 김정윤 | `{모델명}_{imgsz}_v{번호}` |

## 변경 이력
| 버전 | 날짜 | 내용 |
|---|---|---|
| v0.1 | 2026-11-02 | 초안 |
