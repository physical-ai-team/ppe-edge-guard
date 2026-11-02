-- =========================================================
-- violations 테이블 + violation-images 버킷 + RLS + Realtime
-- 기준: docs/interfaces.md ③ (v1.1)
--
-- 적용: Supabase Studio > SQL Editor 에 붙여넣고 Run
--       (또는 Supabase CLI: supabase db push)
-- 여러 번 실행해도 안전하다 (idempotent).
-- =========================================================

-- ---------- 1. 위반 기록 테이블 ----------
-- cloud-sync 가 위반 건만 upsert 한다 (on_conflict=event_id).
create table if not exists public.violations (
  id                    uuid        primary key default gen_random_uuid(),
  event_id              text        not null unique,
  device_id             text        not null,
  captured_at           timestamptz not null,
  received_at           timestamptz not null,
  clock_synced          boolean     not null,
  detected_at           timestamptz not null,
  image_path            text        not null,           -- 'violation-images' 버킷 내 경로
  missing_helmet        boolean     not null,
  missing_vest          boolean     not null,
  person_count          int         not null,
  unknown_helmet_count  int         not null default 0,
  unknown_vest_count    int         not null default 0,
  persons               jsonb       not null default '[]'::jsonb,  -- ② 응답의 persons (박스 오버레이용)
  model_version         text,
  inference_ms          real,
  created_at            timestamptz not null default now()
);

create index if not exists violations_captured_at_idx on public.violations (captured_at desc);
create index if not exists violations_device_id_idx   on public.violations (device_id);

-- ---------- 2. RLS ----------
-- authenticated: select 만 허용
-- 쓰기 정책 없음 → anon/authenticated 의 insert·update·delete 는 모두 거부
-- cloud-sync 는 service_role 키로 쓰므로 RLS 를 우회한다
alter table public.violations enable row level security;

drop policy if exists "authenticated can read violations" on public.violations;
create policy "authenticated can read violations" on public.violations
  for select to authenticated using (true);

-- ---------- 3. Storage (private 버킷) ----------
-- 경로: {device_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg  (UTC)
-- 웹은 signed URL 로만 사진을 본다.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('violation-images', 'violation-images', false, 2097152, array['image/jpeg'])
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "authenticated can read violation images" on storage.objects;
create policy "authenticated can read violation images" on storage.objects
  for select to authenticated using (bucket_id = 'violation-images');

-- ---------- 4. Realtime ----------
-- 웹은 violations 의 INSERT 이벤트를 구독한다.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'violations'
  ) then
    alter publication supabase_realtime add table public.violations;
  end if;
end $$;
