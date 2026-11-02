// 관제 대시보드 — docs/interfaces.md ③ 의 violations 테이블을 읽는다.
// DB 시각은 UTC, 화면 표시만 KST.
import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm";
import { SUPABASE_URL, SUPABASE_ANON_KEY } from "./config.js";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
const BUCKET = "violation-images";
const PAGE = 50;
const SIGNED_URL_SEC = 3600;

const $ = (id) => document.getElementById(id);
const state = { kind: "all", device: "", oldest: null, devices: new Set(), channel: null };

// ---------- 시간 (KST 표시) ----------
const fmtTime = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const fmtClock = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false,
});
function todayStartKST() {
  const d = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
  return { label: d, iso: new Date(`${d}T00:00:00+09:00`).toISOString() };
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// ---------- 인증 ----------
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").textContent = "";
  const { error } = await supabase.auth.signInWithPassword({
    email: $("email").value, password: $("password").value,
  });
  if (error) $("login-error").textContent = "로그인 실패: " + error.message;
});
$("logout").addEventListener("click", () => supabase.auth.signOut());

// 콜백 안에서 supabase 호출을 바로 await 하면 멈출 수 있어 setTimeout 으로 분리
supabase.auth.onAuthStateChange((_event, session) => {
  setTimeout(() => (session ? showApp(session.user) : showLogin()), 0);
});

function showLogin() {
  if (state.channel) supabase.removeChannel(state.channel);
  state.channel = null;
  $("app-view").classList.add("hidden");
  $("login-view").classList.remove("hidden");
}

async function showApp(user) {
  if (!$("app-view").classList.contains("hidden")) return;
  $("login-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("user-email").textContent = user.email;
  await Promise.all([loadDevices(), loadStats(), loadRows(true)]);
  subscribe();
}

// ---------- 카메라 목록 (기록에 나온 device_id) ----------
async function loadDevices() {
  const { data, error } = await supabase.from("violations").select("device_id").limit(1000);
  if (error) return console.error(error);
  data.forEach((r) => addDevice(r.device_id));
}

function addDevice(id) {
  if (!id || state.devices.has(id)) return;
  state.devices.add(id);
  const sel = $("device-filter");
  const opts = [...state.devices].sort();
  sel.length = 1;
  opts.forEach((d) => sel.add(new Option(d, d)));
  sel.value = state.device;
}

// ---------- 오늘 통계 ----------
async function loadStats() {
  const today = todayStartKST();
  $("today").textContent = today.label;
  const { data, error } = await supabase
    .from("violations")
    .select("missing_helmet, missing_vest, person_count, captured_at")
    .gte("captured_at", today.iso)
    .order("captured_at", { ascending: false })
    .limit(10000);
  if (error) return console.error(error);

  const n = (f) => data.filter(f).length;
  $("s-total").textContent = data.length;
  $("s-nohelmet").textContent = n((r) => r.missing_helmet);
  $("s-novest").textContent = n((r) => r.missing_vest);
  $("s-both").textContent = n((r) => r.missing_helmet && r.missing_vest);
  $("s-persons").textContent = data.reduce((sum, r) => sum + r.person_count, 0);
  $("s-last").textContent = data.length ? fmtClock.format(new Date(data[0].captured_at)) : "-";
}

// ---------- 위반 목록 ----------
function applyFilters(q) {
  if (state.kind === "helmet") q = q.eq("missing_helmet", true);
  if (state.kind === "vest") q = q.eq("missing_vest", true);
  if (state.device) q = q.eq("device_id", state.device);
  return q;
}

function matchesFilters(row) {
  if (state.kind === "helmet" && !row.missing_helmet) return false;
  if (state.kind === "vest" && !row.missing_vest) return false;
  if (state.device && row.device_id !== state.device) return false;
  return true;
}

async function loadRows(reset) {
  if (reset) {
    $("rows").innerHTML = "";
    state.oldest = null;
  }
  let q = applyFilters(supabase.from("violations").select("*"))
    .order("captured_at", { ascending: false })
    .limit(PAGE);
  if (state.oldest) q = q.lt("captured_at", state.oldest);

  const { data, error } = await q;
  if (error) return console.error(error);

  const urls = await signedUrls(data);
  for (const row of data) $("rows").append(renderRow(row, urls[row.image_path]));
  if (data.length) state.oldest = data[data.length - 1].captured_at;

  $("more").classList.toggle("hidden", data.length < PAGE);
  $("empty").classList.toggle("hidden", $("rows").children.length > 0);
}

// 사진이 아직 없거나(seed) 지워진 경로는 결과에서 빠진다
async function signedUrls(rows) {
  const paths = rows.map((r) => r.image_path).filter(Boolean);
  if (!paths.length) return {};
  const { data, error } = await supabase.storage.from(BUCKET).createSignedUrls(paths, SIGNED_URL_SEC);
  if (error) { console.error(error); return {}; }
  return Object.fromEntries(data.filter((d) => d.signedUrl).map((d) => [d.path, d.signedUrl]));
}

function violationTags(row) {
  return [row.missing_helmet && "안전모 미착용", row.missing_vest && "조끼 미착용"]
    .filter(Boolean).map((t) => `<span class="tag">${t}</span>`).join("");
}

function renderRow(row, imgUrl) {
  const tr = document.createElement("tr");
  tr.dataset.at = row.captured_at;
  const unknown = row.unknown_helmet_count + row.unknown_vest_count;
  const clockWarn = row.clock_synced
    ? ""
    : ' <span class="clock-warn" title="카메라 시계 미동기화: 게이트웨이 수신 시각으로 표시">⚠</span>';
  const model = [row.model_version, row.inference_ms != null && Math.round(row.inference_ms) + "ms"]
    .filter(Boolean).join(" · ");
  tr.innerHTML = `
    <td>${fmtTime.format(new Date(row.captured_at))}${clockWarn}</td>
    <td>${esc(row.device_id)}</td>
    <td>${violationTags(row)}</td>
    <td>${row.person_count}</td>
    <td>${unknown ? `안전모 ${row.unknown_helmet_count} · 조끼 ${row.unknown_vest_count}` : "-"}</td>
    <td class="muted">${esc(model) || "-"}</td>
    <td>${imgUrl ? `<img class="thumb" src="${esc(imgUrl)}" alt="위반 사진" />` : '<span class="muted nophoto">사진 없음</span>'}</td>`;
  const img = tr.querySelector(".thumb");
  if (img) img.addEventListener("click", () => openPhoto(imgUrl, row));
  return tr;
}

// ---------- 사진 + 박스 오버레이 ----------
// persons[].box 는 원본 이미지 픽셀 좌표 [x1, y1, x2, y2]
function openPhoto(url, row) {
  const img = $("photo-img");
  const svg = $("photo-boxes");
  svg.innerHTML = "";
  img.onload = () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    svg.innerHTML = (row.persons || []).map((p) => {
      const [x1, y1, x2, y2] = p.box;
      const cls = p.helmet === "missing" || p.vest === "missing" ? "bad"
        : p.helmet === "unknown" || p.vest === "unknown" ? "unk" : "ok";
      return `<rect class="${cls}" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" />`;
    }).join("");
  };
  img.src = url;
  const missing = [row.missing_helmet && "안전모", row.missing_vest && "조끼"].filter(Boolean).join(", ");
  $("photo-caption").textContent =
    `${fmtTime.format(new Date(row.captured_at))} · ${row.device_id} · ${missing} 미착용 · ${row.person_count}명`;
  $("photo").showModal();
}

// ---------- 필터 ----------
$("kind-filter").addEventListener("click", (e) => {
  const v = e.target.dataset?.v;
  if (!v) return;
  state.kind = v;
  for (const b of $("kind-filter").children) b.classList.toggle("active", b.dataset.v === v);
  loadRows(true);
});
$("device-filter").addEventListener("change", (e) => {
  state.device = e.target.value;
  loadRows(true);
});
$("more").addEventListener("click", () => loadRows(false));

// ---------- 실시간 ----------
// 밀린 업로드나 seed 처럼 여러 건이 한꺼번에 오면 순서가 섞이므로 captured_at 위치에 끼워 넣는다
function insertSorted(tr) {
  const at = new Date(tr.dataset.at);
  const rows = $("rows");
  const next = [...rows.children].find((r) => new Date(r.dataset.at) < at);
  if (next) rows.insertBefore(tr, next);
  else if ($("more").classList.contains("hidden")) rows.append(tr);
  else return; // 아직 안 불러온 오래된 구간 → "더 보기"로 나온다
  $("empty").classList.add("hidden");
}

function subscribe() {
  state.channel = supabase
    .channel("violations")
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "violations" }, async ({ new: row }) => {
      addDevice(row.device_id);
      loadStats();
      if (!matchesFilters(row)) return;
      const urls = await signedUrls([row]);
      const tr = renderRow(row, urls[row.image_path]);
      tr.classList.add("new");
      insertSorted(tr);
    })
    .subscribe((status) => {
      const on = status === "SUBSCRIBED";
      $("live").className = "live " + (on ? "on" : "off");
      $("live").textContent = on ? "● 실시간" : "● 연결 끊김";
    });
}
