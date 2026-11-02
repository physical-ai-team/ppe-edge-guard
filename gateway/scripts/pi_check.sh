#!/usr/bin/env bash
# 라즈베리파이 게이트웨이 상태 점검 (읽기 전용 — 아무것도 바꾸지 않는다).
# 사용: cd ~/ppe-edge-guard/gateway && bash scripts/pi_check.sh
# 결과를 docs/deploy_raspberry_pi.md "측정 기록" 표와 PR/이슈 코멘트에 붙인다.
set -u

GATEWAY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INGEST_PORT="$(grep -E '^INGEST_PORT=' "$GATEWAY_DIR/.env" 2>/dev/null | cut -d= -f2)"
INGEST_PORT="${INGEST_PORT:-8000}"

ok()   { printf '  [OK]   %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*"; }
section() { printf '\n== %s ==\n' "$*"; }

section "시스템"
printf '  %s / %s / kernel %s\n' "$(. /etc/os-release && echo "$PRETTY_NAME")" "$(uname -m)" "$(uname -r)"
[ "$(uname -m)" = "aarch64" ] && ok "arm64" || warn "aarch64가 아님 — 64-bit OS인지 확인"
if command -v vcgencmd >/dev/null; then
  printf '  온도 %s, 스로틀 %s\n' "$(vcgencmd measure_temp | cut -d= -f2)" "$(vcgencmd get_throttled | cut -d= -f2)"
  [ "$(vcgencmd get_throttled | cut -d= -f2)" = "0x0" ] && ok "전원·발열 스로틀 없음" \
    || warn "스로틀 발생 기록 — 27W 전원 어댑터·쿨러 확인"
fi

section "시각 (received_at·clock_synced 판단 기준)"
timedatectl | sed 's/^/  /'
[ "$(timedatectl show -p NTPSynchronized --value)" = "yes" ] && ok "NTP 동기화됨" \
  || warn "NTP 미동기화 — received_at이 틀릴 수 있음. 네트워크·systemd-timesyncd 확인"

section "메모리·디스크"
free -h | sed 's/^/  /'
df -h / | sed 's/^/  /'
docker system df 2>/dev/null | sed 's/^/  /'

section "네트워크 (ESP32 펌웨어의 GATEWAY_HOST로 쓸 주소)"
hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.' | sed 's/^/  /'

section "Docker"
if command -v docker >/dev/null; then
  docker --version | sed 's/^/  /'
  docker compose version | sed 's/^/  /'
  (cd "$GATEWAY_DIR" && docker compose ps --format 'table {{.Service}}\t{{.Status}}') | sed 's/^/  /'
  docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | sed 's/^/  /'
else
  warn "docker 없음 — 문서 3단계 참고"
fi

section "ingest API"
if curl -fsS "http://127.0.0.1:${INGEST_PORT}/healthz" >/tmp/ppe_healthz 2>/dev/null; then
  ok "healthz $(cat /tmp/ppe_healthz)"
  printf '  stats %s\n' "$(curl -fsS "http://127.0.0.1:${INGEST_PORT}/api/v1/stats")"
else
  warn "http://127.0.0.1:${INGEST_PORT}/healthz 응답 없음 — docker compose logs ingest 확인"
fi
rm -f /tmp/ppe_healthz
