// 계약(docs/interfaces.md ①) 규칙만 모은 모듈. Arduino에 의존하지 않아 PC에서 단위 시험한다.
#pragma once
#include <cstddef>
#include <cstdint>
#include <ctime>

constexpr uint32_t PROTO_MAX_RETRIES = 3;          // 처음 1회 + 재시도 최대 3회
constexpr size_t PROTO_MAX_JPEG_BYTES = 2097152;   // 2 MB, 넘으면 ingest가 413
constexpr time_t PROTO_MIN_VALID_TIME = 1704067200; // 2024-01-01T00:00:00Z, 이전이면 NTP 미동기화로 본다

enum class SendAction { Success, Fatal, Retry };

// ^[a-z0-9-]{3,32}$
bool proto_valid_device_id(const char *id);

// "{boot_rand hex8}-{seq 6자리}" 예: 5e1a9c02-000042
void proto_capture_id(char *out, size_t n, uint32_t boot_rand, uint32_t seq);

// UTC ISO 8601 "YYYY-MM-DDTHH:MM:SSZ". t가 2024년 이전이면 false (헤더를 생략해야 함)
bool proto_iso8601_utc(time_t t, char *out, size_t n);

// 200·202 Success / 4xx Fatal / 5xx·음수(HTTPClient 네트워크 오류) Retry / 그 밖 Fatal
SendAction proto_classify(int http_code);

// attempt 1~3 → 1000·2000·4000ms. retry_after_s >= 0 이면 min(retry_after_s, 4)초
uint32_t proto_retry_delay_ms(int attempt, long retry_after_s);

// 응답 JSON에서 "event_id" 문자열 값을 꺼낸다. 없거나 out이 작으면 false
bool proto_extract_event_id(const char *body, char *out, size_t n);

// FF D8로 시작하고 2 MB 이하인지
bool proto_jpeg_ok(const uint8_t *buf, size_t len);
