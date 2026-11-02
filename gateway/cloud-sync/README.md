# cloud-sync

ingest가 SQLite outbox에 `pending_upload`로 남긴 위반 이벤트를 Supabase에 올리는 서비스다. 담당은 김세광이다.
업로드 형식은 [docs/interfaces.md ③](../../docs/interfaces.md)을 따른다.

```
SQLite events (status=pending_upload)
  → Storage  violation-images/{device_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg   (x-upsert)
  → Table    violations  upsert on_conflict=event_id
  → status=uploaded, uploaded_at 기록
```

HTTP는 컨테이너 헬스체크용 `GET /healthz`(포트 8002, 외부 미공개)만 연다.

## 모드

| `SYNC_MODE` | 동작 | 필요한 값 |
|---|---|---|
| `dry_run` (기본) | `/data/sync-dryrun/` 아래에 Storage와 같은 경로로 사진(`.jpg`)과 upsert 본문(`.jpg.json`)을 기록 | 없음 |
| `supabase` | Supabase Storage·PostgREST REST API를 httpx로 직접 호출 | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (없으면 시작하지 않음) |

service_role 키는 Pi `.env`와 김세광 개발 `.env`에만 둔다.

## Docker로 실행

```powershell
cd gateway
# .env: DEVICE_TOKEN=dev-token, INFERENCE_MODE=mock, SYNC_MODE=dry_run
docker compose up -d --build ingest cloud-sync
conda run -n ppe-ingest python scripts/fake_esp32.py --count 5 --wait
curl.exe http://localhost:8000/api/v1/stats                    # by_status에 uploaded가 보이면 성공
docker compose logs -f cloud-sync
docker compose exec cloud-sync find /data/sync-dryrun -type f   # dry_run 결과
```

**업로드 실패(네트워크 단절) 흉내**

```powershell
docker compose exec cloud-sync chmod -R a-w /data/sync-dryrun   # 쓰기 금지 → 1→2→4…초 재시도 로그
docker compose exec cloud-sync chmod -R u+w /data/sync-dryrun   # 복구 → 다음 재시도에서 uploaded
```

## Docker 없이 실행 (디버깅용)

```powershell
cd gateway/cloud-sync
conda activate ppe-cloud-sync
$env:PYTHONPATH = "..\common"
$env:DATA_DIR = "..\data"          # ingest와 같은 폴더를 가리켜야 한다
$env:SYNC_MODE = "dry_run"
uvicorn app.main:create_app --factory --port 8002
```

## 테스트

```powershell
cd gateway/cloud-sync
conda run -n ppe-cloud-sync python -m pytest -q
```

Supabase 호출은 `httpx.MockTransport`로 대체해서 요청 경로·헤더·본문이 계약과 같은지 검사한다.

## 동작 요약

- **순서**: Storage 업로드가 성공해야 테이블 upsert를 한다. 웹이 사진 없는 행을 보지 않게 하기 위해서다.
- **멱등성**: 사진은 결정적 경로에 `x-upsert: true`, 행은 `event_id` 기준 upsert다. 중간에 실패하면 처음부터 다시 올려도 결과가 같다.
- **재시도**: 모든 실패(연결 오류, 5xx, 4xx 설정 오류 포함)는 1→2→4…초 간격으로 재시도하고, 간격은 `SYNC_MAX_BACKOFF_SEC`를 넘지 않는다. 횟수 제한은 없다. `pending_upload` 사진은 버리지 않는다.
  - 실패 횟수·오류·다음 시도 시각은 `events.sync_attempts`, `sync_error`, `next_sync_at`에 남는다.
  - 사진 파일이 없으면(`image_missing`) 행만 올리지 않고 ERROR 로그를 남긴 채 재시도로 둔다. 정상이라면 일어나지 않는다(ingest cleanup은 `pending_upload` 사진을 지우지 않음).
- **로컬 사진**: 업로드 후에도 지우지 않는다. 보관 기간 정리는 ingest cleanup이 `uploaded_at` 기준으로 한다.
- 이벤트는 `received_at` 순서대로 하나씩 올린다(배치 `SYNC_BATCH_SIZE`=20). 할 일이 없으면 `SYNC_POLL_INTERVAL_SEC`마다 확인한다.
