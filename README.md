# ppe-edge-guard

Edge AI + 클라우드 기반 스마트 산업 안전 시스템 — 안전모/조끼 미착용자 감지.

```
XIAO ESP32S3 ──HTTP──▶ Raspberry Pi 5 (ingest → inference → cloud-sync) ──▶ Supabase ──▶ Web 대시보드
 사람 감지·촬영            YOLOv8n ONNX로 PPE 판별, 위반 건만 업로드          Storage+DB     Realtime 조회
```

| 폴더 | 내용 |
|---|---|
| `firmware/` | XIAO ESP32S3 Sense 펌웨어 (arduino-cli) |
| `gateway/` | 라즈베리파이 docker compose 서비스 (ingest / inference / cloud-sync) |
| `supabase/` | 테이블·RLS·Storage SQL 마이그레이션 |
| `web/` | 관제 대시보드 (GitHub Pages) |
| `training/` | Colab 학습 노트북, ONNX 검증 스크립트 |
| `docs/` | 배포 가이드 |

빌드·실행 명령과 개발 규칙은 [CLAUDE.md](CLAUDE.md)를 참고.

## 빠른 시작 (로컬 conda)

```powershell
conda env create -f gateway/ingest/environment.yml
conda env create -f gateway/inference/environment.yml
conda env create -f gateway/cloud-sync/environment.yml
conda env create -f training/environment.yml
```

비밀값은 템플릿을 복사해서 채운다 (커밋되지 않음):
- `gateway/.env.example` → `gateway/.env`
- `firmware/ppe_cam/secrets.example.h` → `secrets.h` (2단계)
- `web/config.example.js` → `config.js` (6단계)

## 브랜치 규칙

`main`에 직접 push하지 않는다. `feat/<name>` 브랜치 → PR → 병합.
