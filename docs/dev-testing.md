# 단독 개발·테스트 가이드

라즈베리파이 5는 김세광만 가지고 있다. 그래서 **모든 담당자는 Windows 노트북만으로** 자기 파트를 개발하고 테스트할 수 있어야 한다.
다른 파트가 필요하면 아래 **목업(mock)** 이나 **가짜 입력**으로 대체한다. 형식 기준은 [interfaces.md](interfaces.md)다.

> 표의 "제공 브랜치"는 해당 도구가 언제 생기는지를 뜻한다. ⏳는 아직 없음을 뜻한다.

## 공용 도구 (누가 만들고 누가 쓰나)

| 도구 | 역할 | 제공자 / 브랜치 | 사용자 |
|---|---|---|---|
| ingest `INFERENCE_MODE=mock` | inference 없이 시나리오별 가짜 결과를 생성 | 김세광 / `feat/gateway-ingest` ✅ | 김세광, 박민성 |
| ingest `MOCK_SCENARIO` | `both_worn` `helmet_only` `vest_only` `none_worn` `no_person` `random` 중 선택 | 위와 동일 | |
| `gateway/scripts/fake_esp32.py` | ESP32 대신 ①번 요청을 그대로 전송 (폴더의 jpg 순회, 간격·장치ID 지정, `--resend` 중복, `--no-captured-at` NTP 없음, `--wait` 결과 확인) | 김세광 / `feat/gateway-ingest` ✅ | 김세광, 김정윤, 박민성 |
| cloud-sync `SYNC_MODE=dry_run` | Supabase 대신 `/data/sync-dryrun/`에 사진과 JSON을 기록 | 김세광 / `feat/gateway-cloud-sync` ⏳ | 김세광 |
| `supabase/seed.sql` | 가짜 위반 기록 몇 건 (웹 화면 개발용) | 조아람 / `feat/supabase-schema` ⏳ | 조아람 |
| 공개 사전학습 ONNX (`yolov8n` COCO, 416) | PPE 모델 완성 전에 inference 동작 확인용. 사람만 감지하며 helmet/vest는 `unknown` | 김정윤 / `feat/inference-service` ⏳ | 김정윤, 김세광 |
| 테스트 이미지·영상 | 시나리오별 사진·영상. **git에 올리지 않음** → 팀 공유 드라이브 | 이기태 | 전원 |

---

## 박민성 — 펌웨어 (`firmware/`)

1. **빌드만 확인** (장치 없이도 가능)
   ```powershell
   arduino-cli compile --fqbn <FQBN> firmware/ppe_cam
   ```
2. **실제 전송 테스트 (Pi 없이 노트북을 게이트웨이로 사용)**
   - 노트북에서 다음을 실행한다(자세한 내용은 [gateway/ingest/README.md](../gateway/ingest/README.md)).
     ```powershell
     cd gateway; Copy-Item .env.example .env
     # .env: INFERENCE_MODE=mock, DEVICE_TOKEN=dev-token
     docker compose up --build ingest
     ```
   - ESP32 없이 먼저 노트북 안에서 확인한다: `python scripts/fake_esp32.py --count 3 --wait`
   - `ipconfig`로 노트북 IP를 확인하고 `secrets.h`의 `GATEWAY_HOST`에 넣는다.
   - **같은 Wi-Fi**에 연결해야 한다. 학교·회사 Wi-Fi는 기기 간 통신 차단(client isolation)이나 WPA2-Enterprise 때문에 안 되는 경우가 많다. 이럴 때는 **휴대폰 핫스팟**을 쓴다.
   - Windows 방화벽에서 8000번 포트 인바운드를 허용해야 할 수 있다. 관리자 PowerShell에서 실행한다.
     `New-NetFirewallRule -DisplayName "ppe-ingest 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
   - 확인: 시리얼 모니터에 `202`가 찍히는지, `docker compose logs -f ingest`에 수신 로그가 나오는지 본다.
3. **ingest 머지 전**에는 빌드와 시리얼 출력(JPEG 크기, 촬영 소요 시간)으로 검증한다. ingest가 팀장의 바로 다음 작업이므로 임시 수신 서버는 따로 만들지 않는다(중복 작업 방지).
4. Edge Impulse 모델은 EI Studio에서 정확도를 확인한다. 장치 탑재 후에는 시리얼로 감지 점수와 추론 시간을 출력해 확인한다.

## 김정윤 — 학습·inference (`training/`, `gateway/inference/`, `gateway/models/`)

1. **inference 컨테이너 단독 실행**
   ```powershell
   cd gateway
   docker compose up --build inference
   curl.exe http://localhost:8001/healthz
   curl.exe -X POST http://localhost:8001/infer -H "Content-Type: image/jpeg" --data-binary "@<사진>.jpg"
   ```
   compose 내부망 전용 포트는 `docker-compose.dev.yml`에서 노트북에 노출한다.
2. **conda로 컨테이너 없이 실행** (디버깅이 빠름): `conda activate ppe-inference` → `uvicorn` 직접 실행 (명령은 브랜치에서 확정).
3. **계약 준수 확인**: 응답이 [interfaces.md ②](interfaces.md#-ingest--inference)의 필드·값 규칙과 맞는지 테스트 코드로 검사한다(`gateway/inference/tests/`).
4. **정확도 측정**: 이기태 영상에서 뽑은 프레임 + 시나리오 라벨 → 시나리오별 `violation` 정답률을 낸다.
5. **속도 측정**: 노트북 CPU 수치는 참고만 한다. **Pi 5 수치는 김세광에게 측정을 요청**한다(벤치마크 스크립트를 브랜치에 포함).

## 조아람 — Supabase·웹 (`supabase/`, `web/`)

1. **Supabase 프로젝트**
   - 팀 개발용 프로젝트 1개를 만든다(조아람이 소유하고 팀원을 초대).
   - 스키마 실험은 로컬 Supabase CLI(`supabase start`, Docker 필요)나 개발 프로젝트에서 한다.
   - **service_role 키는 김세광에게만 전달한다.** 웹에는 anon 키만 쓴다.
2. **가짜 데이터로 웹 개발**
   - `supabase/seed.sql`로 위반 기록을 넣고, 같은 경로 규칙으로 샘플 사진을 Storage에 올린다.
   - 실시간 확인: Studio SQL Editor에서 `insert into violations ...`를 실행하고 웹에 바로 나타나는지 본다.
3. **로컬 서버**
   ```powershell
   cd web; Copy-Item config.example.js config.js   # URL, anon 키 입력
   python -m http.server 5500
   ```
4. **RLS 확인**
   - 로그아웃 상태에서 anon 키로 `select`를 하면 0건이 나와야 한다.
   - 로그인 상태에서는 조회가 되어야 한다.
   - anon/authenticated로 `insert`를 시도하면 거부되어야 한다.

## 김세광 — ingest·cloud-sync·compose (`gateway/` 중 inference 제외)

1. `INFERENCE_MODE=mock`과 `fake_esp32.py`로 ingest 전 구간(저장 → 상태 전이 → 용량 정리)을 테스트한다.
2. `SYNC_MODE=dry_run`으로 업로드 큐와 재시도를 테스트한다. 네트워크 단절은 dry_run 디렉터리를 쓰기 불가로 바꾸는 식으로 흉내 낸다. 실제 업로드는 조아람의 개발 Supabase 프로젝트로 한다.
3. Pi 통합은 주기적으로 한다. main을 pull하고 `docker compose up -d`를 실행한 뒤 실제 ESP32와 실제 모델로 확인한다. 결과(속도·메모리)는 이슈나 PR 코멘트로 공유한다.

## 이기태 — 검증·시연 영상 (코드 없음)

| 시나리오 ID | 상황 |
|---|---|
| `both_worn` | 안전모 + 조끼 착용 |
| `helmet_only` | 안전모만 착용 |
| `vest_only` | 조끼만 착용 |
| `none_worn` | 둘 다 미착용 |
| `no_person` | 사람 없음 (배경만) |

- **파일명**: `{시나리오ID}_{장소}_{번호}.mp4` (예: `helmet_only_lab_03.mp4`). 시나리오 ID가 곧 정답 라벨이다.
- **촬영 조건**은 실제 카메라 거치와 비슷하게 맞춘다.
  - 높이 약 2~2.5m에서 내려다보는 각도
  - 거리 2~6m
  - 정면, 측면, 뒷모습을 섞는다
  - 밝은 조명과 어두운 조명을 모두 찍는다
  - 1인 장면과 2인 장면을 모두 찍는다(2인은 착용·미착용을 섞는다)
- **보관**: 팀 공유 드라이브. 얼굴이 나오므로 git이나 공개 저장소에 올리지 않는다.
- **용도**: 학습 데이터로 쓰지 않는다. 검증(정답 비교)과 시연에만 쓴다.
