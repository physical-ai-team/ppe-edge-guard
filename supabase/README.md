# supabase

담당: 조아람 · 형식 기준: [docs/interfaces.md ③](../docs/interfaces.md#-cloud-sync--supabase-web이-읽는-형식)

| 파일 | 내용 |
|---|---|
| `migrations/20261102000000_violations.sql` | `violations` 테이블, `violation-images` private 버킷, RLS, Storage 정책, Realtime |
| `seed.sql` | 웹 개발용 가짜 위반 기록 5건 |
| `config.toml` | Supabase CLI 설정 (`supabase init` 으로 생성) |

## 적용 (Supabase CLI)

git 의 `migrations/` 가 DB 의 기준이다. Studio 에서 테이블을 직접 바꾸지 말고 마이그레이션 파일을 추가해서 push 한다.
CLI 는 설치 없이 `npx` 로 실행한다 (Node.js 필요). 명령은 모두 **레포 루트**에서 실행한다.

```powershell
# 처음 한 번
npx supabase@2.122.0 login                                      # 브라우저로 Supabase 로그인
npx supabase@2.122.0 link --project-ref ixfghpjaxeuumaobpueo    # DB 비밀번호 입력 (Project Settings > Database)

# 마이그레이션 적용
npx supabase@2.122.0 migration list    # Local / Remote 비교
npx supabase@2.122.0 db push           # 아직 안 들어간 마이그레이션 적용
npx supabase@2.122.0 db push --include-seed   # seed.sql 까지 (개발 프로젝트만)

# 스키마 변경 시: 새 파일 생성 → SQL 작성 → PR → 머지 후 db push
npx supabase@2.122.0 migration new <이름>
```

CLI 없이 할 때는 Studio > **SQL Editor** 에 마이그레이션 파일을 붙여넣고 Run 해도 된다 (여러 번 실행해도 안전).
이렇게 수동 적용했다면 `npx supabase@2.122.0 migration repair --status applied <버전>` 으로 기록을 맞춘다.

Auth 설정 (CLI 로 push 되지 않으므로 Studio 에서):
1. **Authentication > Users > Add user** 로 관제 계정 생성 (Auto Confirm User 체크)
2. **Authentication > Sign In / Providers** 에서 "Allow new users to sign up" 끄기 (`config.toml` 의 `enable_signup = false` 와 같게)

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
