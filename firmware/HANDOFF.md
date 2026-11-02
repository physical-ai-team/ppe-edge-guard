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
- 참고: `WiFi.reconnect()`는 연결 시도 중이면 아무것도 안 해서 공유기가 꺼졌다 켜지면 영영 안 붙었다 → F2 브랜치에서 `disconnect()+begin()`(15초 간격)으로 고침, 실기로 자동 재연결 확인.

**F2 (`feat/firmware-edge-impulse`) — PR #14 리뷰 중, 모델 v1.0.44 확정**
- [x] `detector_ei.cpp` (DETECTOR_EI 스위치), `build.ps1 -InstallLib`, README "사람 감지 (F2)" 절. 실기: v1.0.43 모델로 사람 앞에서 `trig=person` → ingest 202 → cloud-sync dry_run 업로드까지 (2026-11-02).
- [x] 시연 영상(V1, AI 생성 Veo 3.1, 5개×8초) → 3 fps 프레임 120장 → EI 업로드 → AI labeling(OWL-ViT, `A person (person, 0.2)`) → 재학습 → v1.0.44. 시연 장면 test 100%, 전체 test 54.8%(P 0.92, R 0.57, test 세트가 바뀌어 이전 63%와 직접 비교 불가).
- [x] **v1.0.44로 확정** (발표가 가까워 비교 생략). 시연 영상 화면 재촬영 시 5개 중 4개 촬영, helmet_only는 못 잡음 → README "시연 영상 인식". PERSON_THRESHOLD 0.3(모델 min_score도 바꿈). zip 둘 다 `C:\dev\ppe-data\`(git 밖)에 있음 → 팀 공유 드라이브에 올리기.
- [x] `DETECTOR_EI` 기본값 1, fw 0.2.0, PR #14 리뷰 요청(김세광). F1(PR #9) 머지가 먼저.
- [ ] 모델 zip `C:\dev\ppe-data\ei-ppe-person-fomo-arduino-1.0.44.zip`을 팀 공유 드라이브에 올리기 (사람이 직접)
- [ ] (선택) helmet_only를 꼭 잡아야 하면 타이머 병행 또는 보드 카메라로 찍은 화면 영상 추가 학습
- [ ] (선택) "Wi-Fi 연결됨인데 통신 안 됨" 상태를 한 번 봤다(리셋으로 회복). 전송 4회 실패(code=-1)가 이어지면 Wi-Fi 재시작하는 처리 고려
- [ ] 더 필요하면: 시연 장소에서 보드로 찍은 사진(`c`) 추가 학습 — AI 영상과 보드 카메라 화질 차이가 큼.
- [ ] Edge Impulse 임시 Public 프로젝트 `tmp-121370-import`(ID 1154360) 삭제 (사람이 직접)
- 데이터 위치: 영상·프레임·zip은 `C:\dev\ppe-data\` (저장소 밖, 규칙 13).

## 교훈

- 사용자 폴더 이름이 한글인 PC: ESP32 코어 링크(`cannot find -lxtensa`)와 MinGW g++(TEMP, `crt2.o`)가 실패한다. `firmware/build.ps1`, `firmware/tests/run_tests.ps1`에 우회(subst, TMP 변경, -B/-L)가 들어 있다.
- Windows PowerShell 5.1은 BOM 없는 UTF-8 `.ps1`의 한글을 깨뜨린다 → 스크립트 주석은 영어로.
- 이 저장소 git 작성자는 저장소별 설정(`git config user.name/email`)으로 맞췄다. 새 PC에서는 다시 설정.
