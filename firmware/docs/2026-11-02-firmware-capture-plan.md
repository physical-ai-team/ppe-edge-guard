# F1 펌웨어 촬영·전송 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** XIAO ESP32S3 Sense가 임시 감지(시리얼 `c`·타이머)로 SXGA JPEG을 찍어 interfaces.md ① 형식으로 ingest에 보내고 202를 받는다.

**Architecture:** Arduino 스케치 `firmware/ppe_cam/`. 카메라는 JPEG 모드 하나로 평소 QVGA, 촬영 때만 SXGA로 `set_framesize` 전환(설계 방법 A). 계약 규칙(헤더 값, 응답 분류, 재시도 간격, 시각 형식)은 Arduino에 의존하지 않는 `proto.cpp`에 모아 PC의 g++로 단위 시험한다. 나머지(카메라·Wi-Fi·HTTP)는 컴파일과 보드 실기로 검증한다.

**Tech Stack:** arduino-esp32 코어 3.3.x (`esp_camera`, `WiFi`, `HTTPClient`), arduino-cli(Arduino IDE 내장), MinGW g++(PC 단위 시험), Docker Desktop(ingest mock).

**Spec:** [firmware/docs/2026-11-02-firmware-capture-design.md](2026-11-02-firmware-capture-design.md) — 계약 원문은 [docs/interfaces.md](../../docs/interfaces.md) ①

## Global Constraints

- 수정은 `firmware/` 안에서만. 예외: Task 5의 `CLAUDE.md` 진행 표 F1 행·펌웨어 명령 절(규칙 15).
- 비밀값은 `firmware/ppe_cam/secrets.h`에만(gitignore). 커밋하는 건 `secrets.example.h`.
- 포트는 문서·명령에 `<PORT>`로만 쓴다.
- FQBN `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`.
- 외부 Arduino 라이브러리 추가 금지(ArduinoJson 포함).
- 계약값: 최대 2MB(2097152바이트), 타임아웃 10s, 재시도 최대 3회 1s→2s→4s, 4xx 재시도 금지, NTP 미동기화면 `X-Captured-At` 생략, 동기화 판정 기준 2024-01-01T00:00:00Z(=1704067200).
- `device_id` 정규식 `^[a-z0-9-]{3,32}$`, `X-Capture-Id` 최대 64자 형식 `{hex8}-{순번6}`.
- 줄바꿈 LF.

## Review Focus

1. **게이트웨이가 꺼졌는데 Wi-Fi는 연결됨** → 4번 시도 후 포기하고 `loop`가 계속 돈다(약 47초 이상 멈추지 않음). Task 4 실기 시험 4.
2. **Wi-Fi가 중간에 끊김(핫스팟 끔)** → 촬영 요청은 `skip: no wifi`로 버리고, 다시 켜면 자동 재연결. Task 2 실기 확인.
3. **인터넷 없는 핫스팟이라 NTP가 안 됨** → `X-Captured-At` 헤더를 아예 보내지 않음. Task 1 `iso8601_utc` 시험(1970년 시각 → false) + Task 4 실기.
4. **SXGA JPEG가 2MB 초과이거나 깨진 프레임** → 보내지 않고 시리얼 오류. Task 1 `jpeg_ok` 시험.
5. **부팅 직후 아무것도 안 찍었는데 `r`** → `nothing to resend` 출력, 크래시 없음. Task 4 실기.

---

### Task 1: 계약 규칙 모듈 `proto` + PC 단위 시험

**Files:**
- Create: `firmware/ppe_cam/proto.h`, `firmware/ppe_cam/proto.cpp` (Arduino 헤더 include 금지, `<cstdint> <cstddef> <ctime>`만)
- Test: `firmware/tests/test_proto.cpp`, `firmware/tests/run_tests.ps1`

**Interfaces:**
- Produces (모두 `proto.h`):
  - `bool proto_valid_device_id(const char *id)`
  - `void proto_capture_id(char *out, size_t n, uint32_t boot_rand, uint32_t seq)` — `"%08x-%06u"`
  - `bool proto_iso8601_utc(time_t t, char *out, size_t n)` — `t < 1704067200`이면 false, 아니면 `YYYY-MM-DDTHH:MM:SSZ`
  - `enum class SendAction { Success, Fatal, Retry }; SendAction proto_classify(int http_code)` — 200·202 Success / 400~499 Fatal / 500~599·음수(HTTPClient 네트워크 오류) Retry / 그 밖 Fatal
  - `uint32_t proto_retry_delay_ms(int attempt, long retry_after_s)` — attempt 1~3 → 1000·2000·4000. `retry_after_s >= 0`이면 `min(retry_after_s, 4) * 1000`
  - `bool proto_extract_event_id(const char *body, char *out, size_t n)` — `"event_id"` 키의 문자열 값
  - `bool proto_jpeg_ok(const uint8_t *buf, size_t len)` — `len >= 2 && len <= 2097152 && buf[0]==0xFF && buf[1]==0xD8`
  - `constexpr uint32_t PROTO_MAX_RETRIES = 3;`

- [ ] **Step 1: 실패하는 시험 작성** — `test_proto.cpp`는 외부 프레임워크 없이 `CHECK(cond)` 매크로(실패 시 줄 번호 출력, 끝에 실패 수로 종료 코드). 시험 내용:
  - device_id: `"cam-01"`·`"cam-minsung"` true / `"ab"`(짧음)·`"Cam-01"`(대문자)·`"cam_01"`·33자 문자열 false
  - capture_id: `(0x5e1a9c02, 42)` → `"5e1a9c02-000042"`
  - iso8601: `1793597472` → `"2026-11-02T05:31:12Z"`, `1704067200` → `"2024-01-01T00:00:00Z"`, `0` → false, `1704067199` → false
  - classify: 202·200 → Success, 400·401·413·404 → Fatal, 503·500 → Retry, -1(연결 실패)·-11(타임아웃) → Retry, 302 → Fatal
  - retry_delay: `(1,-1)=1000, (2,-1)=2000, (3,-1)=4000, (1,2)=2000, (1,30)=4000, (2,0)=0`
  - extract_event_id: `{"event_id": "cam-01_20261102T053112Z_a1b2c3", "status": "received"}` → 그 값, `{"error":"invalid_token"}` → false, 출력 버퍼 n이 값보다 작으면 false
  - jpeg_ok: `{0xFF,0xD8,...}` true, `{0x89,0x50}` false, len 0·1 false, len 2097153 false(버퍼는 첫 2바이트만 의미 있게 확인, 길이는 인자로)
- [ ] **Step 2: 실패 확인** — `run_tests.ps1` 내용:
  `g++ -std=c++17 -Wall -I firmware/ppe_cam firmware/tests/test_proto.cpp firmware/ppe_cam/proto.cpp -o firmware/tests/build/test_proto.exe; if ($?) { firmware/tests/build/test_proto.exe }` (build 폴더 없으면 만든다. `firmware/**/build/`는 gitignore 대상)
  Run: `powershell -File firmware/tests/run_tests.ps1` (저장소 루트에서) → Expected: 링크 오류(함수 없음)
- [ ] **Step 3: `proto.cpp` 구현** — `gmtime_r` 대신 MinGW·ESP32 둘 다 되는 `gmtime`(단일 스레드) + `strftime`. event_id 추출은 `strstr`로 `"event_id"` → 다음 `"` 사이.
- [ ] **Step 4: 통과 확인** — 같은 명령 → Expected: `ALL PASS`, 종료 코드 0
- [ ] **Step 5: 커밋** — `git add firmware/ppe_cam/proto.* firmware/tests/` / `git commit -m "firmware: proto rules for capture contract + host tests"`

### Task 2: 스케치 뼈대 · 설정 · Wi-Fi/NTP · 빌드 문서

**Files:**
- Create: `firmware/ppe_cam/ppe_cam.ino`, `config.h`, `secrets.example.h`, `net.h`, `net.cpp`, `firmware/README.md`
- Delete: `firmware/.gitkeep`

**Interfaces:**
- Consumes: `proto_iso8601_utc`
- Produces:
  - `config.h` 매크로(모두 `#ifndef`로 감싸 `secrets.h`에서 덮어쓰기 가능): `DEVICE_ID "cam-01"`, `CAPTURE_FRAMESIZE FRAMESIZE_SXGA`, `CAPTURE_JPEG_QUALITY 12`, `DETECT_FRAMESIZE FRAMESIZE_QVGA`, `CAPTURE_DISCARD_FRAMES 2`, `COOLDOWN_MS 5000`, `DETECTOR_TIMER_MS 0`, `HTTP_TIMEOUT_MS 10000`, `FIRMWARE_VERSION "0.1.0"`, `WIFI_RETRY_MS 5000`
  - `secrets.example.h`: `WIFI_SSID`, `WIFI_PASSWORD`, `GATEWAY_HOST "192.168.0.10"`, `GATEWAY_PORT 8000`, `DEVICE_TOKEN "dev-token"`, 주석 처리된 `// #define DEVICE_ID "cam-minsung"`
  - `ppe_cam.ino`는 `#if __has_include("secrets.h")` → include, 아니면 `#error "secrets.example.h를 secrets.h로 복사하세요"`. 그다음 `config.h`.
  - `net.h`: `void net_begin(); void net_loop(); bool net_connected(); bool net_time_iso(char *out, size_t n);` — `net_loop`는 끊겼으면 `WIFI_RETRY_MS` 간격으로 `WiFi.reconnect()`(막지 않음), 연결 상태가 바뀔 때 시리얼 1줄. `net_begin`은 `WiFi.mode(WIFI_STA)`, `begin`, 최대 15초 대기, `configTime(0, 0, "pool.ntp.org", "time.google.com")`. `net_time_iso`는 `time(nullptr)`을 `proto_iso8601_utc`에 넘김.
- `setup()`: `Serial.begin(115200)`, `Serial.setTxTimeoutMs(0)`(zero-touch 교훈: PC가 시리얼을 안 읽으면 막힘), `net_begin()`, 부팅 정보 1줄(`DEVICE_ID`, 펌웨어 버전, PSRAM 크기).
- `loop()`: `net_loop()`; 10초마다 `[net] wifi=… rssi=… time=…`(시각 없으면 `unsynced`).

- [ ] **Step 1: 파일 작성** (위 인터페이스대로)
- [ ] **Step 2: `firmware/README.md` 작성** — 준비(`secrets.example.h` → `secrets.h` 복사), 컴파일·업로드 명령(CLAUDE.md 형식, 포트는 `<PORT>`), 한글 사용자 폴더 PC 절: zero-touch `docs/04-firmware.md`의 `subst W:/V:` + `ARDUINO_DIRECTORIES_DATA/USER` + `--build-path C:\ppe_build` 절차를 그대로(스케치 경로만 `firmware\ppe_cam`), 단위 시험 명령(`run_tests.ps1`), 시리얼 명령(`c`, `r`)과 로그 형식은 Task 4에서 채운다고 자리만.
- [ ] **Step 3: 컴파일** — README 절차로 `compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi --build-path C:\ppe_build firmware\ppe_cam` (이 PC는 한글 사용자 폴더라 subst 필요. 시험용 `secrets.h`는 example 복사본) → Expected: 성공, 플래시 사용률 출력
- [ ] **Step 4: 실기 (사용자 보드)** — 업로드 후 시리얼: 부팅 줄 → `[net] wifi=connected` → 몇 초 뒤 `time=2026-…Z`. 핫스팟을 끄면 `wifi=disconnected`, 다시 켜면 재연결(Review Focus 2). 보드가 없으면 이 단계는 건너뛰고 Task 4 실기 때 함께 확인한다고 적는다.
- [ ] **Step 5: 커밋** — `firmware: ppe_cam skeleton, config, wifi/ntp, build doc`

### Task 3: 카메라 모듈 (QVGA ↔ SXGA)

**Files:**
- Create: `firmware/ppe_cam/camera.h`, `firmware/ppe_cam/camera.cpp`
- Modify: `firmware/ppe_cam/ppe_cam.ino` (setup에서 `camera_begin()`, 임시 시리얼 명령 `t` = 촬영만 하고 크기·시간 출력 — Task 4에서 `c`로 대체하며 제거)

**Interfaces:**
- Produces:
  - `bool camera_begin();` — 핀은 zero-touch `firmware/zero_touch_cam/zero_touch_cam.ino`의 `CAM_PIN_*` 값 그대로. `pixel_format=PIXFORMAT_JPEG`, `frame_size=CAPTURE_FRAMESIZE`, `jpeg_quality=CAPTURE_JPEG_QUALITY`, `fb_count=2`, `fb_location=CAMERA_FB_IN_PSRAM`, `grab_mode=CAMERA_GRAB_LATEST`, `xclk_freq_hz=20000000`. 초기화 후 `set_framesize(DETECT_FRAMESIZE)`. 실패하면 false(시리얼에 `esp_err` 출력).
  - `camera_fb_t *camera_capture_hires(uint32_t *elapsed_ms);` — `set_framesize(CAPTURE_FRAMESIZE)` → `CAPTURE_DISCARD_FRAMES`장 get/return → 한 장 get 해서 반환(호출자가 반납). 실패 시 nullptr이고 해상도는 DETECT로 되돌린다.
  - `void camera_release_hires(camera_fb_t *fb);` — `esp_camera_fb_return(fb)` 후 `set_framesize(DETECT_FRAMESIZE)`.
  - `camera_fb_t *camera_grab_detect(); void camera_return(camera_fb_t *fb);` — F2용(QVGA 한 장). F1에서는 호출하지 않지만 컴파일되게 둔다.
- [ ] **Step 1: 구현** (위 인터페이스대로)
- [ ] **Step 2: 컴파일** → Expected: 성공
- [ ] **Step 3: 실기** — 시리얼 `t` 5회: 매번 `1280x1024`, `size` 수십~수백 KB, `FF D8` 확인(`proto_jpeg_ok`), 걸린 시간 출력. quality 10과 12의 크기를 적어 둔다(PR에 기록). 연속 5회 중 해상도가 QVGA로 찍히거나 멈추면 멈추고 사용자와 상의(설계 7절: 전환이 불안정하면 다시 상의).
- [ ] **Step 4: 커밋** — `firmware: camera module with QVGA/SXGA switching`

### Task 4: 전송 · 임시 감지 · loop 통합 → ingest 202

**Files:**
- Create: `firmware/ppe_cam/uploader.h`, `uploader.cpp`, `detector.h`, `detector_manual.cpp`
- Modify: `firmware/ppe_cam/ppe_cam.ino` (임시 `t` 제거, 설계 4.7 흐름), `firmware/README.md` (시리얼 명령·로그 형식·노트북 ingest 시험 절차)

**Interfaces:**
- Consumes: Task 1 전부, `net_connected`, `net_time_iso`, `camera_capture_hires`, `camera_release_hires`
- Produces:
  - `detector.h`: `struct DetectResult { bool triggered; const char *trigger; float score; };` `void detector_begin(); DetectResult detector_poll(camera_fb_t *frame);` — `detector_manual.cpp`: 시리얼 `c` → `{true,"serial",-1}`, `DETECTOR_TIMER_MS>0`이고 주기 지남 → `{true,"timer",-1}`. 시리얼 읽기는 `.ino`가 하고 `c`·`r` 문자를 넘기는 방식이 아니라, `detector_manual.cpp`가 `Serial.peek()`로 `c`만 소비하고 나머지 문자는 `.ino`가 처리한다.
  - `uploader.h`: `struct UploadResult { int code; int tries; uint32_t send_ms; char event_id[72]; };` `UploadResult uploader_send(const uint8_t *jpg, size_t len, const char *capture_id, const char *trigger, float score);` — URL `http://GATEWAY_HOST:GATEWAY_PORT/api/v1/captures`, 헤더(설계 4.6), `setTimeout(HTTP_TIMEOUT_MS)`, `collectHeaders`로 `Retry-After` 수집, `proto_classify`로 분기, Retry면 `proto_retry_delay_ms(attempt, retry_after)` 대기 후 다시(최대 `PROTO_MAX_RETRIES`), Fatal이면 응답 본문 시리얼 출력. `X-Captured-At`은 `net_time_iso`가 true일 때만, `X-Detector-Score`는 `score >= 0`일 때만(`%.2f`).
  - `.ino`: 부팅 시 `boot_rand = esp_random()`, `seq` 0부터. 촬영 성공 시 JPEG을 PSRAM `last_jpg`(`ps_malloc`, 크기 바뀌면 재할당)에 복사하고 `last_capture_id` 보관 → `r`은 같은 ID로 `uploader_send` 재호출, 없으면 `nothing to resend`. 쿨다운은 전송이 끝난 시점부터 `COOLDOWN_MS`(성공·실패 모두). Wi-Fi 없으면 `skip: no wifi`, `proto_jpeg_ok` 실패면 `skip: bad jpeg (len=…)` 후 프레임 반납.
  - 요약 로그 한 줄(설계 4.8 형식 그대로): `[cap] id=… trig=… size=…B WxH cap=…ms send=…ms code=… event=… tries=…`
- [ ] **Step 1: 구현**
- [ ] **Step 2: 컴파일 + 단위 시험 재실행** → 둘 다 성공
- [ ] **Step 3: 노트북 ingest 띄우기** — `cd gateway; Copy-Item .env.example .env`(값: `DEVICE_TOKEN=dev-token`, `INFERENCE_MODE=mock`), `docker compose up --build ingest`. 먼저 `conda run -n ppe-ingest python scripts/fake_esp32.py --count 1 --wait`로 ingest 자체가 202를 주는지 확인(ppe-ingest 환경이 없으면 `curl.exe` 예시 요청으로 대신). `gateway/.env`는 gitignore 대상이라 커밋 안 됨. 방화벽 8000 인바운드는 관리자 권한이 필요 → 사용자에게 dev-testing.md 명령을 안내.
- [ ] **Step 4: 실기 시험 (사용자 보드, `secrets.h`의 `GATEWAY_HOST`=노트북 IP, 같은 핫스팟)**
  1. `c` → `code=202`, `event=cam-…`; `curl.exe http://localhost:8000/api/v1/events/<event>` → `trigger: serial`, `clock_synced: true`, `image.width 1280`
  2. `r` → `code=200`
  3. `secrets.h` 토큰을 `wrong`으로 → `code=401 tries=1`, 응답 본문 출력
  4. ingest 정지(`docker compose stop ingest`) 후 `c` → `tries=4`, 약 7초+타임아웃 뒤 포기, 다음 `c`도 받음(Review Focus 1)
  5. 부팅 직후 `r` → `nothing to resend` (Review Focus 5)
  6. `DETECTOR_TIMER_MS 15000`으로 올려 2회 자동 전송 → `trig=timer`
  결과(크기·cap·send ms)를 PR 본문용으로 기록.
- [ ] **Step 5: 커밋** — `firmware: uploader with contract retries, manual detector, capture loop`

### Task 5: 문서 갱신 · PR

**Files:**
- Modify: `CLAUDE.md` — 진행 계획 표 F1 상태 `🔄 PR 리뷰 중`, "펌웨어 (F1에서 확정)" 절에 실제 명령(FQBN, `firmware/README.md` 링크)만. 그 밖의 줄은 건드리지 않음.
- Modify: `firmware/README.md` — Task 3·4 측정값 표

- [ ] **Step 1: 수정 후 `git diff main -- CLAUDE.md`가 F1 행·펌웨어 명령 절만 바뀌었는지 확인**
- [ ] **Step 2: 커밋** — `docs: F1 status and firmware commands`
- [ ] **Step 3: push · PR (사용자 확인 후)** — `git push -u origin feat/firmware-capture`, `gh pr create --base main` 본문: 변경 내용, 검증 방법(Task 1 시험 결과, 컴파일, Task 4 실기 6개 결과와 측정값), 다른 담당자 영향(없음 — 계약 그대로, CLAUDE.md는 규칙 15 범위). 리뷰어 김세광.
