-- =========================================================
-- 웹 대시보드 개발용 가짜 위반 기록 (docs/dev-testing.md)
-- SQL Editor 에서 실행. 실행 시각 기준으로 최근 몇 시간에 걸친 기록이 생긴다.
-- 실행할 때마다 새 event_id 로 추가되므로, 지우려면 맨 아래 delete 문을 쓴다.
--
-- 사진: 행만 생기고 Storage 에는 사진이 없다 (웹에서 "사진 없음"으로 표시).
--       사진까지 보려면 Studio > Storage > violation-images 에서
--       image_path 와 같은 경로로 JPEG 를 올린다.
-- =========================================================

with s(n, device_id, ago, missing_helmet, missing_vest, persons, unknown_vest) as (
  values
    (1, 'cam-01', interval '3 minutes',  true,  false,
        '[{"box":[412,180,655,940],"conf":0.91,"helmet":"missing","vest":"worn"}]'::jsonb, 0),
    (2, 'cam-01', interval '25 minutes', false, true,
        '[{"box":[300,150,560,900],"conf":0.88,"helmet":"worn","vest":"missing"}]'::jsonb, 0),
    (3, 'cam-01', interval '1 hour',     true,  true,
        '[{"box":[500,200,760,980],"conf":0.86,"helmet":"missing","vest":"missing"}]'::jsonb, 0),
    (4, 'cam-02', interval '2 hours',    true,  false,
        '[{"box":[412,180,655,940],"conf":0.91,"helmet":"missing","vest":"worn"},
          {"box":[820,210,1010,900],"conf":0.84,"helmet":"worn","vest":"unknown"}]'::jsonb, 1),
    (5, 'cam-02', interval '5 hours',    false, true,
        '[{"box":[250,120,520,880],"conf":0.79,"helmet":"worn","vest":"missing"}]'::jsonb, 0)
),
t as (
  select s.*,
         date_trunc('second', now() - ago) as captured_at,
         s.device_id || '_' || to_char((now() - ago) at time zone 'UTC', 'YYYYMMDD"T"HH24MISS"Z"')
           || '_seed' || lpad(n::text, 2, '0') as event_id
  from s
)
insert into public.violations (
  event_id, device_id, captured_at, received_at, clock_synced, detected_at, image_path,
  missing_helmet, missing_vest, person_count, unknown_helmet_count, unknown_vest_count,
  persons, model_version, inference_ms
)
select
  event_id, device_id, captured_at, captured_at + interval '1 second', true, captured_at + interval '1 second',
  device_id || '/' || to_char(captured_at at time zone 'UTC', 'YYYY/MM/DD') || '/' || event_id || '.jpg',
  missing_helmet, missing_vest, jsonb_array_length(persons), 0, unknown_vest,
  persons, 'mock-ppe-416-v1', 120 + n * 7
from t
on conflict (event_id) do nothing;

-- 실시간 표시 확인용: 웹을 켜 둔 상태에서 아래 insert 4줄의 맨 앞 "-- " 를 모두 지우고 따로 실행
-- insert into public.violations (event_id, device_id, captured_at, received_at, clock_synced, detected_at, image_path, missing_helmet, missing_vest, person_count, persons)
-- values ('cam-01_' || to_char(now() at time zone 'UTC', 'YYYYMMDD"T"HH24MISS"Z"') || '_live01', 'cam-01', now(), now(), true, now(),
--         'cam-01/' || to_char(now() at time zone 'UTC', 'YYYY/MM/DD') || '/live.jpg', true, false, 1,
--         '[{"box":[412,180,655,940],"conf":0.9,"helmet":"missing","vest":"worn"}]');

-- seed 데이터 삭제
-- delete from public.violations where event_id like '%\_seed__' escape '\' or event_id like '%\_live01' escape '\';
