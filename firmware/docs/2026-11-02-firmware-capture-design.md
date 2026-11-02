# F1 펌웨어 설계 — 촬영·전송 (`feat/firmware-capture`)

- 작성: 박민성 (Claude Code와 함께), 2026-11-02
- 기준: [CLAUDE.md](../../CLAUDE.md) F1 트랙, [docs/interfaces.md](../../docs/interfaces.md) v1.1 ①, [docs/dev-testing.md](../../docs/dev-testing.md) 박민성 절
- 보드: Seeed XIAO ESP32S3 Sense (카메라 OV3660, PSRAM 8MB OPI, 플래시 8MB)

## 1. 목적

사람이 감지되면 고해상도 사진을 한 장 찍어 게이트웨이 ingest에 보낸다.
F1에서는 사람 감지 대신 **임시 감지(타이머·시리얼 입력)**를 쓰고, F2에서 Edge Impulse 모델로 바꾼다.
F2에서 감지 부분만 바꿔 끼울 수 있게 구조를 잡는 것이 F1의 숨은 목표다.

**완료 기준 (CLAUDE.md F1)**: `arduino-cli compile` 성공. 노트북에서 띄운 ingest(`INFERENCE_MODE=mock`)로 보내 202를 받는다.

## 2. 목표 / 비목표

목표
- interfaces.md ① 형식 그대로 전송: raw JPEG body, 필수 헤더 4개, NTP 시각, 응답 코드별 동작
- 고해상도 촬영(기본 SXGA), 해상도·화질은 `config.h` 설정값
- 쿨다운, Wi-Fi 재연결, 전송 재시도(1s → 2s → 4s, 최대 3회, 타임아웃 10s)
- 감지 인터페이스 분리 — F1 임시 감지, F2 Edge Impulse
- 시리얼에 측정값 출력: JPEG 크기, 촬영 시간, 전송 시간, HTTP 코드, `event_id`

비목표 (F1에서 하지 않음)
- Edge Impulse 모델 탑재 (F2)
- 미착용 경고(부저·LED), MQTT — 계약에 없음. 필요하면 interfaces.md v1.2로 따로 합의
- HTTPS, OTA, 절전(deep sleep), 여러 대 동시 운용 시험

하면 안 되는 것
- `firmware/` 밖 수정 (예외: CLAUDE.md 규칙 15에 따라 진행 표의 F1 상태와 펌웨어 명령 절 갱신)
- 비밀값(Wi-Fi 비밀번호, `DEVICE_TOKEN`) 커밋, 포트(COMx) 하드코딩
- 4xx를 받고 재시도하기, 동기화 안 된 시각을 `X-Captured-At`으로 보내기

## 3. 접근 방법 (검토한 것과 고른 것)

카메라 하나로 "감지용 작은 화면"과 "전송용 고해상도 사진"을 둘 다 얻는 방법을 비교했다.

| 방법 | 내용 | 장단점 |
|---|---|---|
| **A. 평소 QVGA, 촬영 때만 SXGA (선택)** | JPEG 모드 하나로 두고 `set_framesize`로 해상도만 바꾼다. 바꾼 직후 1~2장은 버린다 | 감지는 지난번 zero-touch처럼 빠르다(QVGA 디코드 → v19 51ms). 해상도 전환에 수백 ms가 들어 쿨다운에 반영 |
| B. 항상 SXGA, 감지 때 축소 | 가장 단순 | 프레임마다 SXGA JPEG 디코드(수백 ms 이상, PSRAM 약 4MB) → F2에서 느림 |
| C. 촬영 때마다 카메라 재초기화로 형식 전환 | 감지는 원본 RGB/흑백으로 화질 좋음 | 전환 약 1초, 재초기화 반복 시 멈춤 문제가 잦음 |

박민성이 A를 골랐다 (2026-11-02).

## 4. 구조

```
firmware/
  README.md                  빌드·업로드·시험 방법 (한글 경로 PC 우회 포함)
  docs/                      이 문서
  ppe_cam/
    ppe_cam.ino              setup/loop, 상태 흐름
    config.h                 공개 설정값 (커밋)
    secrets.example.h        비밀값 템플릿 (커밋) → secrets.h로 복사 (gitignore)
    camera.{h,cpp}           카메라 초기화, 해상도 전환, 촬영
    net.{h,cpp}              Wi-Fi 재연결, NTP
    uploader.{h,cpp}         ① 전송, 재시도, 응답 해석
    detector.h               감지 인터페이스
    detector_manual.cpp      F1 임시 감지 (타이머·시리얼)
```

### 4.1 설정 (`config.h`, 커밋)
| 이름 | 기본값 | 뜻 |
|---|---|---|
| `DEVICE_ID` | `"cam-01"` | `^[a-z0-9-]{3,32}$`. 개인 시험은 `secrets.h`에서 `cam-minsung`처럼 덮어쓸 수 있게 `#ifndef`로 둔다 |
| `CAPTURE_FRAMESIZE` | `FRAMESIZE_SXGA` | 전송용 해상도 |
| `CAPTURE_JPEG_QUALITY` | `12` | 낮을수록 고화질. 2MB를 넘으면 413이므로 크기를 시리얼로 확인 |
| `DETECT_FRAMESIZE` | `FRAMESIZE_QVGA` | 평소 감지용 해상도 |
| `CAPTURE_DISCARD_FRAMES` | `2` | 해상도 전환 직후 버리는 장 수 |
| `COOLDOWN_MS` | `5000` | 전송 후 다음 촬영까지 최소 간격 (성공·실패 모두) |
| `DETECTOR_TIMER_MS` | `0` | 0이면 꺼짐. 예: 15000이면 15초마다 자동 촬영 (`X-Trigger: timer`) |
| `HTTP_TIMEOUT_MS` | `10000` | 계약값 |
| `FIRMWARE_VERSION` | `"0.1.0"` | `X-Firmware-Version` |

### 4.2 비밀값 (`secrets.h`, gitignore)
`WIFI_SSID`, `WIFI_PASSWORD`, `GATEWAY_HOST`(노트북 IP 또는 Pi), `GATEWAY_PORT`(8000), `DEVICE_TOKEN`(`.env`와 같은 값, 개발은 `dev-token`).
`secrets.h`가 없으면 `#error "secrets.example.h를 secrets.h로 복사하세요"`로 빌드를 멈춘다.

### 4.3 감지 인터페이스 (`detector.h`)
```cpp
struct DetectResult { bool triggered; const char *trigger; float score; };  // score < 0 이면 헤더 생략
void detector_begin();
DetectResult detector_poll(camera_fb_t *frame);   // frame: 감지용 QVGA JPEG (F1 임시 감지는 쓰지 않음, nullptr 가능)
```
- F1 `detector_manual.cpp`: 시리얼 `c`(capture) → `trigger="serial"`. `DETECTOR_TIMER_MS > 0`이면 주기마다 `trigger="timer"`.
- F2에서 `detector_ei.cpp`를 추가하고, `config.h`의 `DETECTOR`(MANUAL/EI) 값으로 한쪽만 컴파일한다. F2 때도 시리얼 `c`는 남겨 둔다(시험용).
- 시리얼 `r`: 마지막 사진을 **같은 `X-Capture-Id`로 다시 전송** → 중복 처리(200) 확인용.

### 4.4 카메라 (`camera.cpp`)
- 초기화는 `CAPTURE_FRAMESIZE`로 한다. 프레임 버퍼를 최대 크기로 PSRAM에 잡기 위해서다(`fb_location=PSRAM`, `fb_count=2`, `grab_mode=CAMERA_GRAB_LATEST` — SXGA JPEG 버퍼 2개는 PSRAM 8MB에 충분). 그다음 `DETECT_FRAMESIZE`로 내린다.
- 핀 배치는 zero-touch `zero_touch_cam.ino`의 XIAO ESP32S3 Sense 값을 그대로 쓴다.
- 촬영: `set_framesize(CAPTURE)` → `CAPTURE_DISCARD_FRAMES`장 버림 → 한 장 촬영 → 전송이 끝날 때까지 프레임 버퍼를 잡고 있음 → 반납 → `set_framesize(DETECT)`.
- JPEG가 `FF D8`로 시작하는지, 2MB 이하인지 보내기 전에 확인한다. 아니면 보내지 않고 시리얼에 오류.

### 4.5 네트워크 (`net.cpp`)
- Wi-Fi: 부팅 시 연결. `loop`마다 상태를 보고, 끊겼으면 5초 간격으로 재연결 시도(막지 않음). 연결 안 된 동안 촬영 요청은 시리얼에 "skip: no wifi"로 남기고 버린다.
- NTP: `configTime(0, 0, "pool.ntp.org", "time.google.com")`. 현재 시각이 2024-01-01 이후일 때만 동기화된 것으로 본다. 아니면 `X-Captured-At`을 **생략**한다.
- 시각 형식: `strftime("%Y-%m-%dT%H:%M:%SZ", gmtime)`.

### 4.6 전송 (`uploader.cpp`) — interfaces.md ①
- `POST http://{GATEWAY_HOST}:{GATEWAY_PORT}/api/v1/captures`, body = JPEG 바이트 그대로 (`HTTPClient::POST(buf, len)`).
- 헤더: `Content-Type: image/jpeg`, `X-Device-Id`, `X-Device-Token`, `X-Capture-Id`, (동기화 시) `X-Captured-At`, `X-Trigger`, (점수 있을 때) `X-Detector-Score`, `X-Firmware-Version`.
- `X-Capture-Id` = `{부팅 시 esp_random() hex8}-{순번 6자리}`. 재시도·`r` 재전송 때 같은 값.
- 응답 처리:

| 결과 | 동작 |
|---|---|
| 202 | 성공. 응답 JSON의 `event_id` 출력 |
| 200 | 성공(중복). `event_id` 출력 |
| 400 / 401 / 413 | 재시도 안 함. 코드와 응답 본문(`error`, `detail`) 출력 |
| 503 | 재시도. `Retry-After`가 있으면 그 초만큼(최대 4초까지만) 기다림 |
| 네트워크 오류·타임아웃·그 밖의 5xx | 재시도 |

- 재시도: 처음 1회 + 최대 3회, 간격 1s → 2s → 4s. 다 실패하면 포기하고 시리얼에 남긴다(사진은 보관하지 않음).
- 전송 중에는 `loop`가 멈춘다(블로킹). 최악은 약 4 × 10s + 7s ≈ 47초. 한 대·시연 규모에서는 감수한다.

### 4.7 `loop` 흐름
```
Wi-Fi 상태 확인/재연결
시리얼 명령 읽기 (c, r)
(F2) 감지용 프레임 얻기
r = detector_poll(frame)
if r.triggered and 쿨다운 지남 and Wi-Fi 연결됨:
    촬영(SXGA) → 전송(재시도 포함) → 프레임 반납 → QVGA 복귀 → 쿨다운 시작
```

### 4.8 시리얼 출력 (한 촬영당 한 줄 요약)
`[cap] id=5e1a9c02-000042 trig=serial size=184322B 1280x1024 cap=412ms send=903ms code=202 event=cam-01_20261102T053112Z_a1b2c3 tries=1`

## 5. 빌드

- FQBN `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`.
- 한글 사용자 폴더 PC는 링크가 실패한다 → zero-touch에서 쓴 `subst` 우회를 `firmware/README.md`에 옮겨 적는다. 영문 사용자 폴더 PC는 해당 없음.
- 외부 라이브러리 없음(ESP32 코어의 `esp_camera`, `WiFi`, `HTTPClient`만). 응답 JSON은 `event_id` 값만 문자열 검색으로 꺼낸다(ArduinoJson 추가 안 함).

## 6. 검증 방법

1. `arduino-cli compile` 성공 (장치 없이).
2. 보드 업로드 후 시리얼: 부팅 → Wi-Fi → NTP 시각 출력.
3. 노트북 ingest(`docker compose up --build ingest`, `INFERENCE_MODE=mock`, `DEVICE_TOKEN=dev-token`)에 보내기:
   - `c` → `code=202`, `event_id` 출력, `GET /api/v1/events/{event_id}`에서 상태 전이 확인
   - `r` → `code=200`(중복)
   - `secrets.h` 토큰을 틀리게 → `401`, 재시도 없음
   - ingest를 끈 채 `c` → 1s/2s/4s 재시도 후 포기
4. 측정해서 PR에 적기: SXGA JPEG 크기(quality 10/12), 해상도 전환+촬영 시간, 전송 시간.

## 7. 박민성이 정한 것 / 구현하며 정할 것

정한 것: HTTP 계약대로(MQTT 접음), 방법 A, 감지 인터페이스 분리.

Claude가 정한 값 (바꿔도 됨): 파일 나누기(4절), `DEVICE_ID` 기본 `cam-01`, `COOLDOWN_MS` 5초, 시리얼 명령 `c`/`r`, 503 `Retry-After` 상한 4초, 실패 사진은 보관 안 함, ArduinoJson 미사용.

구현하며 정할 것: `CAPTURE_DISCARD_FRAMES`와 `CAPTURE_JPEG_QUALITY`의 실제 값(보드 실측 후), `set_framesize` 전환이 OV3660에서 안정적인지(불안정하면 다시 상의).
