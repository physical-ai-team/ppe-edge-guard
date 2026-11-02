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

## 시리얼 출력

115200bps. 10초마다 상태 한 줄:
```
[net] wifi=connected rssi=-58 time=2026-11-02T05:31:12Z
```
`time=unsynced`면 NTP가 아직 안 됐다는 뜻이다(인터넷 없는 핫스팟 등). 이때는 `X-Captured-At` 헤더를 보내지 않는다.
