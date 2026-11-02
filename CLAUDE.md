# CLAUDE.md — ppe-edge-guard

Edge AI + 클라우드 기반 PPE(안전모/조끼) 미착용자 감지 시스템.
**미착용 위반 건만** 사진과 기록을 Supabase에 저장한다.

```
XIAO ESP32S3 (사람 감지 → 고해상도 JPEG)
  → HTTP POST → Raspberry Pi 5 gateway [ingest → inference → cloud-sync]
  → Supabase (private Storage + violations 테이블 + Realtime)
  → web 대시보드 (GitHub Pages, 로그인 필요)
```

## 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 레포 구조, CLAUDE.md, conda 환경, .gitignore/.env.example | ✅ 완료 |
| 2 | 펌웨어 (임시 감지 로직), `arduino-cli compile` 성공 | ⏳ |
| 3 | ingest 컨테이너 + ESP32 사진 수신 테스트 | ⏳ |
| 4 | inference 컨테이너 (공개 사전학습 모델) | ⏳ |
| 5 | Supabase 스키마 + cloud-sync | ⏳ |
| 6 | 웹 대시보드 | ⏳ |
| 7 | Colab 학습 노트북 + 모델 교체 | ⏳ |
| 8 | 라즈베리파이 배포 가이드 | ⏳ |

## 폴더 구조

```
firmware/        XIAO ESP32S3 Arduino 스케치 (arduino-cli)
gateway/
  docker-compose.yml
  .env.example   → .env (compose가 자동으로 읽음, gitignore)
  common/        서비스 공용 Python 코드 (SQLite outbox 큐, 설정, 로깅)
  ingest/        FastAPI: ESP32 이미지 수신, 저장, inference 호출, 로컬 용량 관리
  inference/     FastAPI: YOLOv8n ONNX(416) CPU 추론, 위반 판정 (무상태)
  cloud-sync/    워커: pending_upload → Supabase Storage + 테이블, 재시도
  models/        ONNX 모델 + classes.yaml (볼륨 마운트, *.onnx는 gitignore)
supabase/migrations/  테이블, RLS, Storage 정책 SQL
web/             정적 대시보드 (빌드 없음, supabase-js ESM) → GitHub Pages
training/        Colab 학습 노트북 + 노트북 CPU용 ONNX 검증 스크립트
docs/            배포 가이드 등
```

## 확정된 설계 결정

- **컨테이너 간 통신: HTTP + SQLite outbox.**
  - ingest가 이미지를 저장하고 SQLite `events`에 `received`로 기록한 뒤 202를 반환한다.
  - ingest 워커가 inference에 동기 HTTP로 `POST /infer`를 보낸다.
  - 결과가 위반이면 `pending_upload`, 아니면 `compliant`로 기록한다.
  - cloud-sync가 `pending_upload`를 폴링해서 업로드한다. 성공하면 `uploaded`, 실패하면 지수 백오프로 재시도한다.
  - SQLite(WAL)는 named volume `gateway-data`에 둔다. Windows bind mount에서는 파일 잠금이 불안정하므로 bind mount를 쓰지 않는다.
- **멱등성:** `event_id`는 게이트웨이가 생성하고 Supabase `violations.event_id`는 unique다. Storage 업로드는 결정적 경로에 upsert로 올린다. 재시도해도 중복이 생기지 않는다.
- **로컬 사진 정책** (ingest가 관리):
  - 착용자 사진은 추론 직후 삭제한다. `DEBUG_KEEP_COMPLIANT=true`면 보관한다(기본 off).
  - 업로드 완료된 위반 사진은 `VIOLATION_RETENTION_DAYS`(기본 7일)이 지나면 삭제한다.
  - 사진 폴더가 `LOCAL_IMAGE_MAX_MB`를 넘으면 디버그 보관 착용자 사진, 업로드 완료 위반 사진 순서로 오래된 것부터 삭제한다.
  - `pending_upload` 사진은 절대 삭제하지 않는다. 용량이 넘쳐도 경고 로그만 남긴다.
- **모델:** YOLOv8n, 입력 416. 데이터셋은 Roboflow "Construction Site Safety"(NO-Hardhat / NO-Safety Vest 클래스 포함)다. Colab에서 Roboflow API 키는 Colab Secrets(`ROBOFLOW_API_KEY`)에서 읽는다. 클래스 매핑과 판정 규칙은 `models/classes.yaml`에 두고, 모델을 교체해도 코드는 바꾸지 않는다.
- **이미지 처리:** OpenCV를 쓰지 않는다(메모리·이미지 크기 절약). 전처리는 numpy + Pillow로 한다.
- **Supabase 보안:**
  - Storage 버킷 `violation-images`는 private이다.
  - 웹은 anon 키 + Supabase Auth(이메일/비밀번호) 로그인으로 `authenticated` 역할만 읽는다. 사진은 signed URL로 표시한다.
  - 쓰기 정책은 없다. service_role 키는 Pi `.env`의 cloud-sync에서만 쓴다.
- **컨테이너 공통:**
  - 베이스 이미지는 `mambaorg/micromamba`(amd64/arm64)이고, 각 서비스의 `environment.yml`을 그대로 사용한다.
  - `restart: unless-stopped`, json-file 로그(10m × 3), `/healthz` 헬스체크를 둔다.
  - mem_limit: ingest 256M, inference 1.5G, cloud-sync 256M.

## 개발 환경 / 명령

개발 PC는 Windows(PowerShell)다. CUDA를 쓸 수 없고, conda는 miniforge다. 게이트웨이는 Raspberry Pi 5 4GB(arm64)다.

### conda 환경 (서비스별, Docker 이미지와 동일한 파일)
```powershell
conda env create -f gateway/ingest/environment.yml       # ppe-ingest
conda env create -f gateway/inference/environment.yml    # ppe-inference
conda env create -f gateway/cloud-sync/environment.yml   # ppe-cloud-sync
conda env create -f training/environment.yml             # ppe-training
# 의존성 변경 후: conda env update -f <file> --prune
```

### 펌웨어 (2단계에서 확정)
```powershell
# FQBN: esp32:esp32:XIAO_ESP32S3 (+ PSRAM=opi)
arduino-cli compile --fqbn <FQBN> firmware/ppe_cam
arduino-cli upload  --fqbn <FQBN> -p <PORT> firmware/ppe_cam   # <PORT>는 사용자가 알려줌. 하드코딩 금지
```

### 게이트웨이 (3단계 이후)
```powershell
cd gateway; Copy-Item .env.example .env   # 값 채우기
docker compose up -d --build
```

## 규칙

1. **main에 직접 push 금지.** 단계/기능별로 `feat/<name>` 브랜치에서 작업하고 브랜치만 push한다. 병합은 사용자가 PR로 한다.
2. **비밀값 커밋 금지.**
   - 비밀값은 `firmware/**/secrets.h`, `gateway/.env`, `web/config.js`에만 둔다. 모두 gitignore 대상이다.
   - 대신 각각의 `*.example*` 템플릿을 커밋한다.
   - service_role 키는 Pi `.env`에만 둔다.
3. **업로드 포트(COMx)는 하드코딩하지 않는다.** 문서와 명령에는 `<PORT>`로 쓴다.
4. 모델 파일(`*.onnx`, `*.pt`)은 git과 Docker 이미지에 넣지 않는다. `gateway/models/` 볼륨으로 마운트한다.
5. 줄바꿈은 LF로 통일한다(`.gitattributes`). Pi에서 실행되는 스크립트와 Dockerfile이 CRLF로 깨지는 것을 막기 위해서다.
6. 의존성을 추가할 때는 해당 서비스의 `environment.yml`을 수정한다. Docker와 로컬이 같은 파일을 쓴다.
7. 각 단계가 끝나면 이 파일의 **진행 상태**와 **명령** 섹션을 갱신한다.
