// Wi-Fi 연결·재연결, NTP 시각
#pragma once
#include <cstddef>

void net_begin();                          // 연결 시도(최대 15초) + NTP 시작
void net_loop();                           // 끊겼으면 WIFI_RETRY_MS 간격으로 재연결 (막지 않음)
bool net_connected();
bool net_time_iso(char *out, size_t n);    // NTP 동기화됐으면 UTC ISO 8601, 아니면 false
