# firmware — XIAO ESP32S3 Sense 카메라

담당: 박민성. 사람이 감지되면 고해상도 JPEG을 찍어 게이트웨이 ingest로 보낸다. 형식은 [docs/interfaces.md ①](../docs/interfaces.md)을 따른다.
설계는 [docs/2026-11-02-firmware-capture-design.md](docs/2026-11-02-firmware-capture-design.md)에 있다.

| 경로 | 내용 |
|---|---|
| `ppe_cam/` | Arduino 스케치 |
| `ppe_cam/proto.*` | 계약 규칙(헤더 값, 응답 분류, 재시도 간격, 시각). Arduino 없이 PC에서 시험 |
| `tests/` | `proto` 단위 시험 (PC g++) |
| `build.ps1` | 컴파일·업로드 (한글 사용자 폴더 PC 우회 포함) |

## 준비

1. Arduino IDE 2.x 설치 → 보드 매니저에서 **esp32 by Espressif 3.3.x** 설치 (이 PC는 3.3.12로 확인).
2. 비밀값 파일 만들기 — **커밋 금지**(gitignore 대상):
   ```powershell
   Copy-Item firmware/ppe_cam/secrets.example.h firmware/ppe_cam/secrets.h
   ```
   `WIFI_SSID`, `WIFI_PASSWORD`, `GATEWAY_HOST`(노트북이나 Pi의 IP), `DEVICE_TOKEN`(gateway `.env`와 같은 값)을 채운다.
   개인 시험 장치는 `#define DEVICE_ID "cam-minsung"`처럼 이름을 바꿔도 된다.
3. 다른 설정(해상도, 화질, 쿨다운, 타이머)은 `ppe_cam/config.h`에 있다. `secrets.h`에서 같은 이름을 먼저 정의하면 덮어쓴다.

## 빌드·업로드 (저장소 루트에서)

```powershell
powershell -File firmware/build.ps1                 # 컴파일만
powershell -File firmware/build.ps1 -Port <PORT>    # 컴파일 + 업로드 (포트는 장치 관리자에서 확인)
```

- FQBN은 `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`다. 카메라 버퍼에 PSRAM이 필요하다.
- 빌드 산출물은 `C:\ppe_build`에 생긴다(저장소 밖).
- **사용자 폴더 이름이 한글인 PC**는 ESP32 코어 링크가 `cannot find -lxtensa`로 실패한다. `build.ps1`이 이를 감지해 코어 폴더를 임시 드라이브(`subst`)로 연결하고, 끝나면 연결을 푼다. 영문 사용자 폴더 PC는 해당 없음.
- Arduino IDE에서 직접 열어도 된다: 보드 **XIAO_ESP32S3**, 도구 → PSRAM **OPI PSRAM**.

## 단위 시험

```powershell
powershell -File firmware/tests/run_tests.ps1    # ALL PASS 가 나와야 한다
```
PC에 g++(MinGW, 예: `winget install BrechtSanders.WinLibs.POSIX.UCRT`)가 필요하다. 한글 사용자 폴더 PC 우회도 스크립트에 들어 있다.

## 시리얼 명령·출력

115200bps. 줄바꿈 설정은 상관없다.

| 입력 | 동작 |
|---|---|
| `c` | 지금 SXGA로 한 장 찍어 전송 (`X-Trigger: serial`) |
| `r` | 마지막 사진을 **같은 `X-Capture-Id`로** 다시 전송 → ingest가 `200`(중복)을 돌려줘야 정상 |

`config.h`의 `DETECTOR_TIMER_MS`를 0보다 크게 하면 그 주기마다 자동으로 찍는다(`X-Trigger: timer`).
촬영 후 `COOLDOWN_MS`(기본 5초) 동안은 다음 촬영을 건너뛴다.

촬영 한 번에 요약 한 줄:
```
[cap] id=5e1a9c02-000042 trig=serial size=184322B 1280x1024 cap=412ms send=903ms code=202 event=cam-01_20261102T053112Z_a1b2c3 tries=1
```
- `cap`: 해상도 전환 + 버리는 프레임 + 촬영에 걸린 시간 / `send`: 전송(재시도 대기 포함)
- `code`: 마지막 HTTP 코드. 음수는 네트워크 오류(-1 연결 거부, -11 타임아웃)
- 4xx면 재시도하지 않고 응답 본문을 `[up] code=401 (no retry) body=...`로 출력한다
- 네트워크 오류·5xx는 1s → 2s → 4s 간격으로 최대 3번 더 시도한다(503은 `Retry-After`를 최대 4초까지 따름)

10초마다 상태 한 줄:
```
[net] wifi=connected rssi=-58 time=2026-11-02T05:31:12Z
```
`time=unsynced`면 NTP가 아직 안 됐다는 뜻이다(인터넷 없는 핫스팟 등). 이때는 `X-Captured-At` 헤더를 보내지 않고, ingest가 `clock_synced=false`로 기록한다.

## 노트북 ingest로 실기 시험 (Pi 없이)

[docs/dev-testing.md](../docs/dev-testing.md) 박민성 절과 같다.

1. 노트북에서 ingest 띄우기
   ```powershell
   cd gateway; Copy-Item .env.example .env
   # .env: DEVICE_TOKEN=dev-token, INFERENCE_MODE=mock
   docker compose up -d --build ingest
   curl.exe http://localhost:8000/healthz      # {"status":"ok","inference_mode":"mock"}
   ```
2. `ipconfig`로 노트북 IP를 보고 `secrets.h`의 `GATEWAY_HOST`에 넣는다. 보드와 노트북은 **같은 Wi-Fi**(학교 Wi-Fi는 기기 간 통신이 막혀 있는 경우가 많으니 휴대폰 핫스팟 권장).
3. Windows 방화벽 8000 인바운드 허용(관리자 PowerShell, 한 번만):
   `New-NetFirewallRule -DisplayName "ppe-ingest 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
4. 업로드 후 시리얼에서 확인할 것

| # | 할 일 | 기대 결과 |
|---|---|---|
| 1 | `c` | `code=202`, `event=cam-…`. `curl.exe http://localhost:8000/api/v1/events/<event>` → `trigger: serial`, `image.width: 1280` |
| 2 | `r` | `code=200` (중복) |
| 3 | `secrets.h` 토큰을 `wrong`으로 바꿔 업로드 후 `c` | `code=401 tries=1`, 응답 본문 출력 |
| 4 | `docker compose stop ingest` 후 `c` | `tries=4`로 포기, 그 뒤 `c`도 정상 동작 |
| 5 | 부팅 직후 `r` | `nothing to resend` |
| 6 | `DETECTOR_TIMER_MS 15000`으로 업로드 | 15초마다 `trig=timer` |

### 실기 시험 결과 (2026-11-02, XIAO ESP32S3 + OV3660, 노트북 ingest mock)

보드는 공유기 2.4GHz(`iptime_ipsbi`), 노트북은 같은 공유기 5GHz에 연결(같은 192.168.0.x면 대역이 달라도 된다).

| # | 결과 |
|---|---|
| 1 | ✅ `code=202`, `trigger: serial`, 1280×1024, `captured_at` = 촬영 순간, `clock_synced=true` |
| 2 | ✅ `code=200`, 같은 `event_id` |
| 3 | ✅ `code=401 (no retry)`, 본문 `invalid_token` |
| 4 | ✅ `tries=4`로 포기(`send=47016ms` = 타임아웃 10 s×4 + 대기 1+2+4 s, 계약대로). ingest 재시작 후 `r` → 202, `captured_at`은 처음 촬영 시각 유지. 그 뒤 `c`도 202 |
| 5 | ✅ `nothing to resend` |
| 6 | ✅ 15초마다 `trig=timer`, 202 |

| 측정 | 값 |
|---|---|
| SXGA JPEG 크기 | 40~50 KB (7장: 40.4~49.8 KB) |
| `cap` (QVGA→SXGA 전환 + 촬영) | 223~242 ms |
| `send` (202, 연결 안정 후) | 214~1291 ms. 부팅 직후 첫 전송 3~4.6 s |
| `send` (중복 200) | 609~746 ms |
| RSSI | -58 ~ -80 dBm |

- 해상도 전환은 7장 모두 1280×1024로 정상, 멈춤 없음.
- 신호가 약하면(-75 dBm 이하) 부팅 때 15초 안에 Wi-Fi가 안 붙을 수 있다. 이후 자동 재연결로 붙는다. 그 사이 `E wifi:sta is connecting, return error` 로그는 무해하다.

## 사람 감지 (F2, Edge Impulse)

보드가 평소 QVGA 프레임으로 사람을 감지하고, 감지되면 SXGA로 찍어 보낸다(`X-Trigger: person`, `X-Detector-Score`). 시리얼 `c`도 그대로 된다.

### 라이브러리 설치 (PC마다 한 번)
모델 라이브러리 zip은 git에 넣지 않는다(규칙 12) → 팀 공유 드라이브 `ei-ppe-person-fomo-arduino-<버전>.zip`.
```powershell
powershell -File firmware/build.ps1 -InstallLib <zip 경로>   # 설치 후 컴파일. 새 버전도 같은 명령으로 덮어쓴다
```
직접 받으려면 Edge Impulse 프로젝트 `ppe-person-fomo`(ID 1154357) → Deployment → **Arduino library**, **Quantized (int8)**, EON Compiler → Build.

### 켜기
`secrets.h`(개인) 또는 `config.h`에서:
```c
#define DETECTOR_EI 1     // 0이면 F1 시리얼·타이머 감지 (라이브러리 없이 빌드됨)
#define DETECT_DEBUG 1    // 추론마다 [det] person=... 출력 (조정할 때만)
```
| 설정 | 기본 | 뜻 |
|---|---|---|
| `PERSON_THRESHOLD` | 0.4 | person 점수 기준. 놓치는 것보다 오탐이 낫다(Pi가 거름) |
| `DETECT_INTERVAL_MS` | 200 | 추론 간격 |
| `DETECT_CONSECUTIVE` | 2 | 연속 몇 번 넘어야 촬영 |
| `COOLDOWN_MS` | 5000 | 촬영 후 쉬는 시간. 이 동안은 추론도 안 한다 |

### 실기 결과 (2026-11-02, 모델 v1.0.43)
- 추론 dsp 2 ms + nn 32 ms (EI 추정 391 ms보다 훨씬 빠름, ESP32-S3 ESP-NN)
- 1~3 m 앞 사람: `person=0.50~0.69` → `trig=person` → SXGA 촬영 → ingest 202, `detector_score` 저장됨 → cloud-sync dry_run 업로드까지 확인
- 사람 없을 때 `person=0.00`

### 주의
- `crop_and_interpolate_rgb888`은 dst에 잘라낸 크기(QVGA면 240×240×3)로 먼저 쓴다. dst를 모델 크기로 잡으면 힙이 깨진다 → 같은 버퍼에서 처리(`detector_ei.cpp`).
- EI SDK의 `ei_calloc`은 IDF 5.x에서 정렬이 안 돼 esp-nn에서 힙이 깨질 수 있다 → `detector_ei.cpp`에서 16바이트 정렬로 덮어쓴다.
