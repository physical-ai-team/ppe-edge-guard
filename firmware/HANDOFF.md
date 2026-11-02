# firmware HANDOFF (박민성)

> 이어서 작업할 때: 저장소 루트 `CLAUDE.md`(팀 규칙) → 이 파일의 **남은 일** → 필요하면 `firmware/README.md`, `firmware/docs/`.
> 내 담당은 `firmware/`뿐이다. 다른 폴더는 담당자 확인 없이 고치지 않는다. main 직접 push 금지(브랜치 → PR → 김세광 머지).

## 현재 상태 (2026-11-02)

- 브랜치 `feat/firmware-capture`(F1) — push됨, **PR 아직 안 올림**.
- 계약: `docs/interfaces.md` v1.1 ① 그대로 — HTTP POST raw JPEG `/api/v1/captures`, `X-Device-Id` 필수. (처음엔 MQTT로 정했다가 팀 계약이 이미 HTTP로 확정돼 있어 HTTP로 바꿈. 미착용 경고를 보드로 돌려보내는 기능은 계약에 없음 — 하려면 v1.2 합의 필요)
- 설계 [docs/2026-11-02-firmware-capture-design.md](docs/2026-11-02-firmware-capture-design.md), 계획 [docs/2026-11-02-firmware-capture-plan.md](docs/2026-11-02-firmware-capture-plan.md).
- 완료: 계획 Task 1~3, Task 4 코드, Task 5 문서. 컴파일 성공(플래시 32%, 경고 없음), `firmware/tests/run_tests.ps1` ALL PASS.
- 노트북 ingest(Docker, `INFERENCE_MODE=mock`)에 펌웨어와 같은 헤더로 curl 시험: 202 / 같은 ID 재전송 200 / 잘못된 토큰 401 / 시각 헤더 없음 → `clock_synced=false` 확인.
- **아직 못 한 것: 실제 보드 시험** (카메라 해상도 전환, Wi-Fi, 전송 전부 보드에서는 미확인).

## 남은 일

**F1 마무리**
- [ ] 노트북과 보드를 **2.4GHz** Wi-Fi(또는 폰 핫스팟)에 같이 연결. 이 PC 기본 Wi-Fi `iptime_ipsbi_5G`는 5GHz라 ESP32가 못 붙는다.
- [ ] Windows 방화벽 8000 인바운드 허용(관리자 PowerShell, 한 번만): `New-NetFirewallRule -DisplayName "ppe-ingest 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
- [ ] `firmware/ppe_cam/secrets.h` 만들기(`secrets.example.h` 복사, gitignore). `GATEWAY_HOST` = 노트북 IP(`ipconfig`), `DEVICE_TOKEN=dev-token`
- [ ] `cd gateway; docker compose up -d --build ingest` (`.env`: `DEVICE_TOKEN=dev-token`, `INFERENCE_MODE=mock`)
- [ ] `powershell -File firmware/build.ps1 -Port <PORT>`로 업로드 → `firmware/README.md` "노트북 ingest로 실기 시험" 표의 6개 시험
  - 1번(`c` → 202)에서 `/api/v1/events/<id>`의 `captured_at`이 촬영 순간인지도 확인 (재시도해도 안 밀리게 고친 부분)
  - 카메라 해상도 전환(QVGA↔SXGA)이 불안정하면(크기가 QVGA로 찍히거나 멈춤) 설계 7절대로 다시 상의
  - SXGA JPEG 크기, `cap`/`send` ms를 기록 → README에 측정값 표 추가
- [ ] 시험 결과를 넣어 PR(`feat/firmware-capture` → main, 리뷰어 김세광). PR 본문: 변경 내용, 검증(단위 시험·컴파일·실기 6개·측정값), 영향(없음 — 계약 그대로, CLAUDE.md는 규칙 15 범위). PR 올릴 때 루트 `CLAUDE.md` F1 상태를 `🔄 PR 리뷰 중`으로.

**F2 (`feat/firmware-edge-impulse`, F1 머지 후)**
- [ ] Edge Impulse 프로젝트 `ppe-person-fomo` (계정 minff, ID 1154357, Private): 공개 126387 + 121370(라벨 hum→person) 합쳐 603장, FOMO MobileNetV2 0.1, 64×64 RGB, 60 epoch 증강. 시험 정확도 63.4%, 검증 재현율 0.63, ESP-EYE 추정 391ms. 합쳐도 원본보다 나아지지 않았음.
- [ ] 다음 시도: 판정 기준 0.5 → 낮추기(사람 놓치는 게 더 치명적, 오탐은 Pi가 거름), 보드 카메라로 찍은 시연 장소 사진 추가 학습
- [ ] Arduino 라이브러리로 내보내기 → `detector_ei.cpp`(`detector.h` 인터페이스) — `camera_grab_detect()`로 QVGA 프레임을 받아 판정. zero-touch 교훈: EI SDK `ei_calloc` 16바이트 정렬 문제(코어 3.x에서 힙 깨짐) → 정렬된 `ei_calloc`을 펌웨어에 넣기, `fmt2rgb888`은 RGB 순서(BGR로 뒤집지 말 것)
- [ ] Edge Impulse 임시 Public 프로젝트 `tmp-121370-import`(ID 1154360) 삭제 (사람이 직접)

## 교훈

- 사용자 폴더 이름이 한글인 PC: ESP32 코어 링크(`cannot find -lxtensa`)와 MinGW g++(TEMP, `crt2.o`)가 실패한다. `firmware/build.ps1`, `firmware/tests/run_tests.ps1`에 우회(subst, TMP 변경, -B/-L)가 들어 있다.
- Windows PowerShell 5.1은 BOM 없는 UTF-8 `.ps1`의 한글을 깨뜨린다 → 스크립트 주석은 영어로.
- 이 저장소 git 작성자는 저장소별 설정(`git config user.name/email`)으로 맞췄다. 새 PC에서는 다시 설정.
