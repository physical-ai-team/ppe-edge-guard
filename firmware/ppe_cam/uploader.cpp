#include "uploader.h"

#include <Arduino.h>
#include <HTTPClient.h>

#include "proto.h"
#include "settings.h"

static int post_once(const uint8_t *jpg, size_t len, const char *capture_id, const char *captured_at,
                     const char *trigger, float score, long *retry_after_s, String *body) {
  HTTPClient http;
  char url[96];
  snprintf(url, sizeof url, "http://%s:%d/api/v1/captures", GATEWAY_HOST, GATEWAY_PORT);
  if (!http.begin(url)) return HTTPC_ERROR_CONNECTION_REFUSED;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  const char *keys[] = {"Retry-After"};
  http.collectHeaders(keys, 1);

  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-Id", DEVICE_ID);
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.addHeader("X-Capture-Id", capture_id);
  if (captured_at) http.addHeader("X-Captured-At", captured_at);  // 미동기화면 생략 (계약)
  if (trigger) http.addHeader("X-Trigger", trigger);
  if (score >= 0) {
    char sc[8];
    snprintf(sc, sizeof sc, "%.2f", score);
    http.addHeader("X-Detector-Score", sc);
  }
  http.addHeader("X-Firmware-Version", FIRMWARE_VERSION);

  int code = http.POST(const_cast<uint8_t *>(jpg), len);
  *retry_after_s = -1;
  if (code > 0) {
    *body = http.getString();
    String ra = http.header("Retry-After");
    if (ra.length() > 0) *retry_after_s = ra.toInt();
  }
  http.end();
  return code;
}

UploadResult uploader_send(const uint8_t *jpg, size_t len, const char *capture_id, const char *captured_at,
                           const char *trigger, float score) {
  UploadResult r = {};
  uint32_t start = millis();
  for (uint32_t attempt = 0; attempt <= PROTO_MAX_RETRIES; attempt++) {
    long retry_after = -1;
    String body;
    r.code = post_once(jpg, len, capture_id, captured_at, trigger, score, &retry_after, &body);
    r.tries = attempt + 1;
    SendAction action = proto_classify(r.code);
    if (action == SendAction::Success) {
      if (!proto_extract_event_id(body.c_str(), r.event_id, sizeof r.event_id)) r.event_id[0] = '\0';
      break;
    }
    if (action == SendAction::Fatal) {
      Serial.printf("[up] code=%d (no retry) body=%s\n", r.code, body.c_str());
      break;
    }
    if (attempt == PROTO_MAX_RETRIES) {
      Serial.printf("[up] code=%d, giving up after %d tries\n", r.code, r.tries);
      break;
    }
    // 503이 아닌데 Retry-After가 붙어 있어도 계약상 의미가 없으므로 503일 때만 따른다
    uint32_t wait = proto_retry_delay_ms(attempt + 1, r.code == 503 ? retry_after : -1);
    Serial.printf("[up] code=%d, retry %d in %lums\n", r.code, attempt + 1, (unsigned long)wait);
    delay(wait);
  }
  r.send_ms = millis() - start;
  return r;
}
