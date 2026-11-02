# firmware HANDOFF (박민성)

> 이어서 작업할 때: 저장소 루트 `CLAUDE.md`(팀 규칙) → 이 파일의 **남은 일** → 필요하면 `firmware/README.md`, `firmware/docs/`.
> 내 담당은 `firmware/`뿐이다. 다른 폴더는 담당자 확인 없이 고치지 않는다. main 직접 push 금지(브랜치 → PR → 김세광 머지).

## 현재 상태 (2026-11-02, 실기 시험 후)

- 브랜치 `feat/firmware-capture`(F1) — push됨, **PR 아직 안 올림**.
- 계약: `docs/interfaces.md` ① 그대로 (v1.2는 게이트웨이 내부 상태·통계만 바뀌어 펌웨어 영향 없음) — HTTP POST raw JPEG `/api/v1/captures`, `X-Device-Id` 필수. (처음엔 MQTT로 정했다가 팀 계약이 이미 HTTP로 확정돼 있어 HTTP로 바꿈. 미착용 경고를 보드로 돌려보내는 기능은 계약에 없음 — 하려면 계약 개정(v1.3) 합의 필요)
- 설계 [docs/2026-11-02-firmware-capture-design.md](docs/2026-11-02-firmware-capture-design.md), 계획 [docs/2026-11-02-firmware-capture-plan.md](docs/2026-11-02-firmware-capture-plan.md).
- 완료: 계획 Task 1~3, Task 4 코드, Task 5 문서. 컴파일 성공(플래시 32%, 경고 없음), `firmware/tests/run_tests.ps1` ALL PASS.
- 노트북 ingest(Docker, `INFERENCE_MODE=mock`)에 펌웨어와 같은 헤더로 curl 시험: 202 / 같은 ID 재전송 200 / 잘못된 토큰 401 / 시각 헤더 없음 → `clock_synced=false` 확인.
- 보드 실기 시험 6개 통과(카메라 해상도 전환, Wi-Fi, 전송, 재시도, 재전송, 타이머).

## 남은 일

**F1 마무리**
- [x] 보드 실기 시험 6개 전부 통과 (2026-11-02). 결과·측정값은 `firmware/README.md` "실기 시험 결과". 보드 2.4GHz `iptime_ipsbi`, 노트북 5GHz(같은 공유기라 OK), 방화벽 규칙 추가됨, 보드 포트는 이 PC에서 COM10.
- [ ] PR(`feat/firmware-capture` → main, 리뷰어 김세광). 본문: 변경 내용, 검증(단위 시험·컴파일·실기 6개·측정값), 영향(없음 — 계약 그대로, CLAUDE.md는 규칙 15 범위). CLAUDE.md F1 상태는 `🔄 PR 리뷰 중`으로 바꿔 둠.
- 참고: 부팅 때 신호 약하면 Wi-Fi 15초 안에 못 붙고 나중에 붙음(무해). 필요하면 `net_loop`에서 연결 중일 땐 `reconnect()` 생략.

**F2 (`feat/firmware-edge-impulse`, F1 머지 후)**
- [ ] Edge Impulse 프로젝트 `ppe-person-fomo` (계정 minff, ID 1154357, Private): 공개 126387 + 121370(라벨 hum→person) 합쳐 603장, FOMO MobileNetV2 0.1, 64×64 RGB, 60 epoch 증강. 시험 정확도 63.4%, 검증 재현율 0.63, ESP-EYE 추정 391ms. 합쳐도 원본보다 나아지지 않았음.
- [ ] **결정(2026-11-02): 시간이 없어 이기태 시연 영상(V1)이 나오면 그 프레임으로 재학습한다.** 영상에서 1~2 fps로 프레임 추출 → EI 업로드 → `person` 박스 라벨 → 재학습. 판정 기준 0.5 → 낮추기(사람 놓치는 게 더 치명적, 오탐은 Pi가 거름).
  - 폰 영상은 보드 카메라(OV3660)와 색·화각이 달라 성능이 떨어질 수 있다 → 시연 장소에서 보드로 찍은 사진(`c`로 촬영한 ingest 사진)도 섞는다.
  - 얼굴 나온 영상·프레임은 git 금지(규칙 13), 공유 드라이브에서만. EI 프로젝트는 Private 유지.
  - 영상이 늦으면 대안: 시연은 F1 타이머 트리거(예: 3~5초)로 하고 사람 판정은 Pi에 맡긴다(이미 실기 통과).
- [ ] Arduino 라이브러리로 내보내기 → `detector_ei.cpp`(`detector.h` 인터페이스) — `camera_grab_detect()`로 QVGA 프레임을 받아 판정. zero-touch 교훈: EI SDK `ei_calloc` 16바이트 정렬 문제(코어 3.x에서 힙 깨짐) → 정렬된 `ei_calloc`을 펌웨어에 넣기, `fmt2rgb888`은 RGB 순서(BGR로 뒤집지 말 것)
- [ ] Edge Impulse 임시 Public 프로젝트 `tmp-121370-import`(ID 1154360) 삭제 (사람이 직접)

## 교훈

- 사용자 폴더 이름이 한글인 PC: ESP32 코어 링크(`cannot find -lxtensa`)와 MinGW g++(TEMP, `crt2.o`)가 실패한다. `firmware/build.ps1`, `firmware/tests/run_tests.ps1`에 우회(subst, TMP 변경, -B/-L)가 들어 있다.
- Windows PowerShell 5.1은 BOM 없는 UTF-8 `.ps1`의 한글을 깨뜨린다 → 스크립트 주석은 영어로.
- 이 저장소 git 작성자는 저장소별 설정(`git config user.name/email`)으로 맞췄다. 새 PC에서는 다시 설정.
