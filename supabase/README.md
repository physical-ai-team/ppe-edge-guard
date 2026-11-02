# supabase

담당: 조아람 · 형식 기준: [docs/interfaces.md ③](../docs/interfaces.md#-cloud-sync--supabase-web이-읽는-형식)

| 파일 | 내용 |
|---|---|
| `migrations/20261102000000_violations.sql` | `violations` 테이블, `violation-images` private 버킷, RLS, Storage 정책, Realtime |
| `seed.sql` | 웹 개발용 가짜 위반 기록 5건 |

## 적용

1. Studio > **SQL Editor** 에 `migrations/` 파일을 붙여넣고 Run (여러 번 실행해도 안전)
2. 웹 개발용 데이터가 필요하면 `seed.sql` 도 Run
3. **Authentication > Users > Add user** 로 관제 계정 생성 (Auto Confirm User 체크)
4. **Authentication > Sign In / Providers** 에서 "Allow new users to sign up" 끄기

## 키 배포

| 키 | 어디에 | 누구 |
|---|---|---|
| Project URL + publishable(anon) 키 | `web/config.js` (gitignore) | 웹 |
| secret(service_role) 키 | Pi `gateway/.env` 의 `SUPABASE_SERVICE_ROLE_KEY` | **김세광만** |

## RLS 확인 체크리스트 (S1 완료 기준)

PowerShell, `$U` = Project URL, `$K` = publishable 키:

```powershell
# 1) 로그아웃 상태 select → [] (0건)
curl.exe -s "$U/rest/v1/violations?select=event_id" -H "apikey: $K"

# 2) anon insert → 401, "violates row-level security policy"
curl.exe -s -X POST "$U/rest/v1/violations" -H "apikey: $K" -H "Content-Type: application/json" -d '{\"event_id\":\"x\"}'

# 3) 가입 차단 → 422 "signup_disabled"
curl.exe -s -X POST "$U/auth/v1/signup" -H "apikey: $K" -H "Content-Type: application/json" -d '{\"email\":\"t@example.com\",\"password\":\"Test-12345678\"}'
```

4) 로그인 상태 조회 / authenticated insert 거부 → 웹 대시보드에서 확인 (목록 표시됨, 쓰기 UI 없음)
