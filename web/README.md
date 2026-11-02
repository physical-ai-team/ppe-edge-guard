# web — 관제 대시보드

담당: 조아람 · 데이터: Supabase `violations` ([docs/interfaces.md ③](../docs/interfaces.md#-cloud-sync--supabase-web이-읽는-형식))

빌드 도구 없는 정적 페이지(HTML + ES module). supabase-js 는 CDN 에서 불러온다.

## 로컬 실행

```powershell
cd web; Copy-Item config.example.js config.js   # URL, publishable(anon) 키 입력
python -m http.server 5500                       # http://localhost:5500
```

`index.html` 을 더블클릭으로 열면 ES module 이 막히므로 반드시 서버로 연다.

## 배포 (GitHub Pages)

`main` 에 `web/` 변경이 머지되면 [.github/workflows/pages.yml](../.github/workflows/pages.yml) 이 자동 배포한다.
`config.js` 는 gitignore 라서 workflow 가 URL·publishable 키로 만들어 넣는다.

- 주소: https://physical-ai-team.github.io/ppe-edge-guard/
- 수동 재배포: GitHub > Actions > "Deploy web to Pages" > Run workflow
- 처음 한 번 (레포 관리자): Settings > Pages > Source = **GitHub Actions**

## 기능

- 이메일/비밀번호 로그인 (Supabase Auth, 가입 차단 — 계정은 Studio 에서 생성)
- 오늘(KST) 위반 통계: 위반 건수, 안전모/조끼/둘 다 미착용, 감지 인원, 마지막 위반 시각
- 위반 목록: 안전모/조끼/카메라 필터, 50건씩 더 보기
- Realtime: `violations` INSERT 시 목록과 통계 즉시 갱신
- 사진: private 버킷 `violation-images` 를 signed URL(1시간)로 표시, 클릭 시 `persons` 박스 오버레이
  - 빨강 = 미착용, 초록 = 모두 착용, 주황 점선 = 판단불가 포함
- `clock_synced = false` 행은 ⚠ 표시 (카메라 시계 미동기화)

## 테스트

1. `supabase/seed.sql` 실행 → 목록에 5건 (사진은 "사진 없음")
2. 웹을 켜 둔 채 `seed.sql` 아래쪽 주석의 실시간 insert 문 실행 → 새 행이 바로 나타남
3. 사진 확인: Studio > Storage > `violation-images` 에 행의 `image_path` 와 같은 경로로 JPEG 업로드 → 새로고침 시 썸네일
