#include "proto.h"

#include <cstdio>
#include <cstring>

bool proto_valid_device_id(const char *id) {
  if (!id) return false;
  size_t len = std::strlen(id);
  if (len < 3 || len > 32) return false;
  for (size_t i = 0; i < len; i++) {
    char c = id[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
  }
  return true;
}

void proto_capture_id(char *out, size_t n, uint32_t boot_rand, uint32_t seq) {
  std::snprintf(out, n, "%08lx-%06lu", (unsigned long)boot_rand, (unsigned long)seq);
}

bool proto_iso8601_utc(time_t t, char *out, size_t n) {
  if (t < PROTO_MIN_VALID_TIME) return false;
  struct tm *tm = std::gmtime(&t);  // 단일 스레드에서만 호출
  if (!tm) return false;
  return std::strftime(out, n, "%Y-%m-%dT%H:%M:%SZ", tm) > 0;
}

SendAction proto_classify(int http_code) {
  if (http_code == 200 || http_code == 202) return SendAction::Success;
  if (http_code < 0) return SendAction::Retry;  // HTTPClient 연결 실패·타임아웃 등
  if (http_code >= 500 && http_code <= 599) return SendAction::Retry;
  return SendAction::Fatal;  // 4xx 및 예상 밖 코드: 재시도하지 않음
}

uint32_t proto_retry_delay_ms(int attempt, long retry_after_s) {
  if (retry_after_s >= 0) return (uint32_t)(retry_after_s > 4 ? 4 : retry_after_s) * 1000u;
  if (attempt < 1) attempt = 1;
  if (attempt > 3) attempt = 3;
  return 1000u << (attempt - 1);
}

bool proto_extract_event_id(const char *body, char *out, size_t n) {
  if (!body || !out || n == 0) return false;
  const char *key = std::strstr(body, "\"event_id\"");
  if (!key) return false;
  const char *p = std::strchr(key + 10, ':');
  if (!p) return false;
  p = std::strchr(p, '"');
  if (!p) return false;
  p++;
  const char *end = std::strchr(p, '"');
  if (!end) return false;
  size_t len = (size_t)(end - p);
  if (len + 1 > n) return false;
  std::memcpy(out, p, len);
  out[len] = '\0';
  return true;
}

bool proto_jpeg_ok(const uint8_t *buf, size_t len) {
  if (!buf || len < 2 || len > PROTO_MAX_JPEG_BYTES) return false;
  return buf[0] == 0xFF && buf[1] == 0xD8;
}
