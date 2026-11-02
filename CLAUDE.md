# CLAUDE.md — ppe-edge-guard

> 팀원 5명이 함께 쓰는 **기준 문서**다. 사람이든 Claude Code든 작업 전에 이 파일을 먼저 읽는다.
> 서비스 간 데이터 형식은 [docs/interfaces.md](docs/interfaces.md)가, 단독 테스트 방법은 [docs/dev-testing.md](docs/dev-testing.md)가 기준이다.

Edge AI + 클라우드 기반 PPE(안전모/조끼) 미착용자 감지 시스템이다.
**미착용 위반 건만** 사진과 기록을 Supabase에 저장한다.

```
XIAO ESP32S3 (사람 감지 → 고해상도 JPEG)
  → HTTP POST → Raspberry Pi 5 gateway [ingest → inference → cloud-sync]
  → Supabase (private Storage + violations 테이블 + Realtime)
  → web 대시보드 (GitHub Pages, 로그인 필요)
```

## 팀 / 담당

| 이름 | 담당 | 브랜치 접두어 |
|---|---|---|
| 김세광 (팀장) | 게이트웨이(`ingest`, `cloud-sync`), docker compose, Pi 셋업·배포, 카메라 거치, 통합 테스트, PR 리뷰·머지 | `feat/gateway-*`, `feat/infra-*` |
| 박민성 | ESP32 펌웨어, Edge Impulse 데이터 수집·라벨링·학습·탑재 | `feat/firmware-*` |
| 김정윤 | YOLOv8 학습, ONNX export, `inference` 컨테이너, 정확도·속도 측정 | `feat/inference-*`, `feat/training-*` |
| 조아람 | Supabase 스키마·Auth·RLS, 웹 대시보드, 발표 자료 | `feat/web-*`, `feat/supabase-*` |
| 이기태 | 테스트·시연 영상 (착용/미착용 상황별). 코드 작업 없음 | — |

### 폴더별 담당자

| 경로 | 담당 |
|---|---|
| `firmware/` | 박민성 |
| `training/`, `gateway/inference/`, `gateway/models/` | 김정윤 |
| `gateway/ingest/`, `gateway/cloud-sync/`, `gateway/common/`, `gateway/scripts/`, `gateway/docker-compose*.yml`, `gateway/.env.example` | 김세광 |
| `supabase/`, `web/` | 조아람 |
| `docs/interfaces.md` | 공동 (변경 시 관련 담당자 전원 승인) |
| `CLAUDE.md`, `docs/` (그 외), `.github/`, 루트 설정 파일 | 김세광 |

리뷰어 자동 지정은 [.github/CODEOWNERS](.github/CODEOWNERS)로 한다.

## 진행 계획

### 0. 기반 (김세광)
| 단계 | 내용 | 상태 |
|---|---|---|
| 0-1 | 레포 구조, CLAUDE.md, conda 환경, .gitignore/.env.example | ✅ 완료 (PR #1) |
| 0-2 | 팀 역할, 브랜치 규칙, `docs/interfaces.md` **v1.0 확정**, 단독 테스트 가이드, CODEOWNERS | ✅ 완료 (PR #2) |

### 1. 병렬 트랙 (인터페이스 v1.x 기준으로 동시에 진행)

| 트랙 | 담당 | 브랜치 | 내용 | 완료 기준 | 상태 |
|---|---|---|---|---|---|
| G1 | 김세광 | `feat/gateway-ingest` | **최우선.** ingest 컨테이너, compose(ingest), `INFERENCE_MODE=mock`, `fake_esp32.py` | 팀원 노트북에서 `docker compose up ingest`를 실행하고 `fake_esp32.py`로 전송하면 202 응답이 오고, `/api/v1/events/{id}`에서 상태 전이가 확인됨 | ✅ 완료 (PR #3) |
| F1 | 박민성 | `feat/firmware-capture` | 감지 인터페이스 + 임시 감지(타이머/시리얼), 고해상도 촬영, ① 형식으로 전송, 쿨다운, 재연결, 재시도 | `arduino-cli compile` 성공. G1 이후 노트북 ingest로 202 수신 | ⏳ |
| I1 | 김정윤 | `feat/inference-service` | inference 컨테이너, 공개 사전학습 모델(COCO yolov8n 416), `classes.yaml`, ② 형식 응답 | 노트북에서 단독으로 `curl /infer` 시 계약 형식 응답. 계약 테스트 통과 | ⏳ |
| S1 | 조아람 | `feat/supabase-schema` | `violations` 테이블, private 버킷, RLS, Storage 정책, Auth, `seed.sql` | RLS 확인 체크리스트 통과 (dev-testing.md) | 🔄 PR 리뷰 중 (개발 프로젝트 적용·RLS 체크리스트 통과) |
| W1 | 조아람 | `feat/web-dashboard` | 로그인, 목록, Realtime, signed URL 사진, GitHub Pages 배포 | seed와 수동 insert가 실시간으로 표시됨 | ⏳ (S1 이후) |
| G2 | 김세광 | `feat/gateway-cloud-sync` | cloud-sync, `SYNC_MODE=dry_run`, 재시도·백오프 | dry_run 통과 후 개발 Supabase에 실제 업로드 | 🔄 dry_run 완료·PR 리뷰 중 (실업로드는 S1 이후) |
| T1 | 김정윤 | `feat/training-ppe` | Colab 노트북(Roboflow, Colab Secrets), ONNX 416 export, `validate_onnx.py`, 정확도·속도 측정 | 시나리오별 정답률 보고, 모델을 Drive로 공유 | ⏳ |
| F2 | 박민성 | `feat/firmware-edge-impulse` | EI 데이터 수집·학습, `detector_ei`, EI 라이브러리 설치 문서화 | 실기에서 사람 감지 시 촬영·전송 | ⏳ (F1 이후) |
| V1 | 이기태 | — | 시나리오 5종 검증·시연 영상 (dev-testing.md의 촬영 가이드) | 공유 드라이브에 시나리오별 업로드 | ⏳ |

### 2. 통합 마일스톤 (김세광)
| 마일스톤 | 내용 | 조건 |
|---|---|---|
| M1 | 노트북 E2E: fake_esp32 → ingest → inference(사전학습) → cloud-sync → 웹 | G1, I1, G2, S1, W1 |
| M2 | Pi E2E: 실제 ESP32(임시 감지) → Pi → Supabase → 웹. Pi 속도·메모리 측정 | M1, F1 |
| M3 | 학습 모델 + EI 펌웨어로 교체 | M2, T1, F2 |
| M4 | 이기태 영상 기준으로 시나리오별 검증, 시연 리허설, `docs/deploy_raspberry_pi.md` 완성 | M3, V1 |

## 확정된 설계 결정

- **컨테이너 간 통신: HTTP + SQLite outbox.**
  - ingest가 이미지를 저장하고 SQLite `events`에 `received`로 기록한 뒤 202를 반환한다.
  - ingest 워커가 inference에 `POST /infer`(**JPEG 바이트를 직접 전송**, 공유 볼륨 경로 아님)를 보낸다.
  - 결과가 위반이면 `pending_upload`, 아니면 `compliant`로 기록한다.
  - cloud-sync가 `pending_upload`를 폴링해서 업로드한다. 성공하면 `uploaded`, 실패하면 지수 백오프로 재시도한다.
  - 네트워크·5xx·타임아웃·429는 무한 재시도한다. 그 밖의 4xx와 사진 파일 없음은 영구 오류로 보고, `SYNC_MAX_PERMANENT_FAILURES`회(기본 5) 쌓이면 `upload_failed`로 바꾸고 재시도를 멈춘다(interfaces.md v1.2).
  - SQLite(WAL)는 named volume `gateway-data`에 둔다. Windows bind mount에서는 파일 잠금이 불안정하므로 bind mount를 쓰지 않는다.
- **시각:**
  - 모든 시각은 UTC로 다룬다. DB와 Storage 경로도 UTC이고, KST 변환은 웹 화면 표시에서만 한다.
  - `captured_at`(ESP32 NTP 시각), `received_at`(ingest 수신 시각), `detected_at`(추론 완료 시각)을 따로 기록한다.
  - ESP32 시각이 없거나 이상하면 `captured_at`에 `received_at`을 쓰고 `clock_synced=false`로 표시한다.
- **촬영 해상도**는 계약으로 고정하지 않는다. 펌웨어 설정값(`CAPTURE_FRAMESIZE`)으로 두고 기본값은 SXGA다.
- **멱등성:**
  - ESP32는 `X-Capture-Id`를 보내고, ingest가 이 값으로 중복을 제거한다.
  - `event_id`는 ingest가 만든다. Supabase `violations.event_id`는 unique다.
  - Storage 업로드는 결정적 경로에 upsert로 올린다.
- **로컬 사진 정책** (ingest가 관리):
  - 착용자 사진은 추론 직후 삭제한다. `DEBUG_KEEP_COMPLIANT=true`면 보관한다(기본 off).
  - 업로드 완료된 위반 사진은 `VIOLATION_RETENTION_DAYS`(기본 7일)이 지나면 삭제한다.
  - 사진 폴더가 `LOCAL_IMAGE_MAX_MB`를 넘으면 디버그 보관 착용자 사진, 업로드 완료 위반 사진 순서로 오래된 것부터 삭제한다.
  - `pending_upload`·`upload_failed` 사진은 절대 삭제하지 않는다. 용량이 넘쳐도 경고 로그만 남긴다.
- **모델:**
  - YOLOv8n, 입력 416. 데이터셋은 Roboflow "Construction Site Safety"다.
  - Colab에서 Roboflow API 키는 Colab Secrets(`ROBOFLOW_API_KEY`)에서 읽는다.
  - inference는 응답에서 클래스를 정규화 이름 5종(`person` `helmet` `no_helmet` `vest` `no_vest`)으로 바꾼다. 모델별 매핑은 이름 기준으로 `models/classes.yaml`에 둔다.
  - 모델 버전 이름은 `yolov8n-ppe-416-v1` 형식이고, ONNX 파일명과 같다.
  - 착용 여부를 판단할 수 없는 `unknown`은 위반이 아니다. 대신 `unknown_helmet_count`·`unknown_vest_count`를 기록한다. 모든 이벤트의 통계는 ingest 로컬 SQLite에 남기고 `GET /api/v1/stats`로 조회한다. Supabase에는 위반 건만 올라간다.
- **이미지 처리:** OpenCV를 쓰지 않는다. 전처리는 numpy + Pillow로 한다.
- **Supabase 보안:**
  - Storage 버킷 `violation-images`는 private이다.
  - 웹은 anon 키 + 이메일/비밀번호 로그인으로 `authenticated` 역할만 읽는다. 사진은 signed URL로 표시한다.
  - `violations.persons`는 jsonb로 저장한다(웹에서 박스 오버레이용).
  - 쓰기 정책은 없다. service_role 키는 Pi `.env`의 cloud-sync와 김세광의 개발 `.env`에서만 쓴다.
- **컨테이너 공통:**
  - 베이스 이미지는 `mambaorg/micromamba`(amd64/arm64)이고, 각 서비스의 `environment.yml`을 그대로 사용한다.
  - `restart: unless-stopped`, json-file 로그(10m × 3), `/healthz` 헬스체크를 둔다.
  - mem_limit: ingest 256M, inference 1.5G, cloud-sync 256M.
- **단독 실행 모드:** ingest는 `INFERENCE_MODE=mock`, cloud-sync는 `SYNC_MODE=dry_run`으로 다른 서비스 없이 실행할 수 있다.

## 개발 환경 / 명령

- 팀원 PC는 Windows(PowerShell)이고 CUDA를 쓸 수 없다.
- 라즈베리파이 5 4GB(arm64)는 **김세광만** 가지고 있다. ESP32는 여러 팀원이 가지고 있다.

### conda 환경 (서비스별, Docker 이미지와 동일한 파일)
```powershell
conda env create -f gateway/ingest/environment.yml       # ppe-ingest
conda env create -f gateway/inference/environment.yml    # ppe-inference
conda env create -f gateway/cloud-sync/environment.yml   # ppe-cloud-sync
conda env create -f training/environment.yml             # ppe-training
# 의존성 변경 후: conda env update -f <file> --prune
```

### 펌웨어 (F1에서 확정)
```powershell
# FQBN: esp32:esp32:XIAO_ESP32S3 (+ PSRAM=opi)
arduino-cli compile --fqbn <FQBN> firmware/ppe_cam
arduino-cli upload  --fqbn <FQBN> -p <PORT> firmware/ppe_cam   # <PORT>는 각자 확인. 하드코딩 금지
```

### 게이트웨이
```powershell
cd gateway; Copy-Item .env.example .env    # 값 채우기 (단독 테스트: DEVICE_TOKEN=dev-token, INFERENCE_MODE=mock, SYNC_MODE=dry_run)
docker compose up -d --build                # 전체 (현재 ingest, cloud-sync)
docker compose up --build ingest            # ingest 단독, 로그 보기
docker compose logs -f ingest cloud-sync
docker compose exec cloud-sync find /data/sync-dryrun -type f   # dry_run 업로드 결과
docker compose exec cloud-sync python -m app.requeue            # upload_failed → pending_upload (원인 수정 후)
docker compose down                         # 정지 (데이터 유지) / down -v: 데이터 볼륨까지 삭제

# 가짜 ESP32 전송 (ppe-ingest 환경)
conda run -n ppe-ingest python scripts/fake_esp32.py --count 3 --wait
curl.exe http://localhost:8000/api/v1/stats
```

### 라즈베리파이 (김세광)
배포 절차는 [docs/deploy_raspberry_pi.md](docs/deploy_raspberry_pi.md)를 따른다.
```bash
cd ~/ppe-edge-guard && git pull --ff-only && cd gateway && docker compose up -d --build   # 업데이트 배포
bash scripts/pi_check.sh        # 시각·메모리·디스크·컨테이너·API 점검 (읽기 전용)
# Pi에서는 docker compose down -v 금지 (위반 사진 볼륨 삭제)
```

### 테스트 (서비스 폴더에서)
```powershell
cd gateway/ingest; conda run -n ppe-ingest python -m pytest -q
cd gateway/cloud-sync; conda run -n ppe-cloud-sync python -m pytest -q
```

### gateway Python 코드 구조
- 서비스 코드는 `gateway/<service>/app/`, 공용 코드는 `gateway/common/ppe_common/`(SQLite outbox 스키마, 상태 상수, 시각·경로 규칙)에 둔다.
- import 경로는 Docker에서 `PYTHONPATH=/app`이고, 공용 코드는 `/app/ppe_common`에 복사된다. 로컬에서는 `PYTHONPATH=..\common`으로 맞춘다. 테스트는 `pytest.ini`의 `pythonpath`로 처리한다.
- Dockerfile 빌드 컨텍스트는 `gateway/`다. 이미지는 `mambaorg/micromamba:2.0.5`를 쓰고 `mambauser`로 실행한다.
- 이벤트 상태 전이: `received → inferring → compliant | pending_upload → uploaded | upload_failed`, 추론 영구 오류는 `infer_failed`. 정의는 `ppe_common/db.py`에 있다.
- 스키마를 바꾸면 `ppe_common/db.py`의 `SCHEMA_VERSION`을 올리고, 기존 볼륨용 컬럼 추가는 `_MIGRATIONS`에 넣는다.

## 규칙

### 브랜치·PR
1. **main에 직접 push하지 않는다.** 모든 변경은 브랜치 → PR → 김세광 리뷰·머지 순서로 들어간다.
2. 브랜치 이름은 위 표의 **본인 접두어**를 쓴다: `feat/<영역>-<주제>` (예: `feat/firmware-capture`).
3. 작업 시작 전 `git pull`로 main을 최신으로 맞추고 브랜치를 만든다. PR은 작게 나눠서 자주 올린다.
4. PR 본문에는 변경 내용, **검증 방법(직접 실행한 결과)**, 다른 담당자에게 영향이 있는지를 적는다.

### 담당 영역
5. **다른 담당자 폴더는 수정 전에 그 담당자에게 확인받는다.** 오타 수정 같은 작은 변경도 마찬가지다. 담당자를 PR 리뷰어로 지정한다.
6. **`docs/interfaces.md` 변경은 관련 담당자 전원이 승인해야 한다.** 계약을 바꾸는 코드 변경은 계약 문서 PR이 먼저 머지된 뒤에 올린다.
7. **Claude Code로 작업할 때:**
   - 작업 전에 사용자가 누구인지(위 팀 표 기준) 확인한다.
   - 사용자의 담당 폴더 밖을 수정해야 하면 **수정하지 말고 멈춘다.** 어느 담당자에게 무엇을 확인받아야 하는지 사용자에게 알린다.
   - 다른 파트가 필요하면 직접 구현하지 않는다. `docs/dev-testing.md`의 목업이나 가짜 입력을 쓴다.

### 실행 환경
8. 모든 gateway 컨테이너는 **팀원의 Windows Docker Desktop(amd64)에서 단독 실행·테스트**할 수 있어야 한다.
   - Pi(arm64) 전용 의존성이나 Pi 하드웨어 전제는 쓰지 않는다.
   - Pi 실측과 통합은 김세광이 주기적으로 한다.
9. 의존성을 추가할 때는 해당 서비스의 `environment.yml`을 수정한다. Docker와 로컬이 같은 파일을 쓴다. conda-forge에 linux-aarch64 빌드가 있는지 확인한다.

### 보안·데이터
10. **비밀값은 커밋하지 않는다.**
    - 비밀값은 `firmware/**/secrets.h`, `gateway/.env`, `web/config.js`에만 둔다. 모두 gitignore 대상이다.
    - 대신 각각의 `*.example*` 템플릿을 커밋한다.
    - service_role 키는 김세광과 Pi에만 둔다.
11. 업로드 포트(COMx)는 하드코딩하지 않는다. 문서와 명령에는 `<PORT>`로 쓴다.
12. 모델 파일(`*.onnx`, `*.pt`)은 git과 Docker 이미지에 넣지 않는다. `gateway/models/` 볼륨으로 마운트하고 팀 공유 드라이브로 배포한다.
13. 사람 얼굴이 나오는 사진·영상(테스트·시연용)은 git에 올리지 않는다. 팀 공유 드라이브에 둔다.
14. 줄바꿈은 LF로 통일한다(`.gitattributes`).

### 문서 갱신
15. 트랙이 끝나면 담당자는 이 파일의 **진행 계획** 표 상태와 **명령** 섹션을 자기 PR에서 갱신한다.
