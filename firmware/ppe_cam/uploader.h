// interfaces.md ① POST /api/v1/captures 전송 (재시도 포함)
#pragma once
#include <cstddef>
#include <cstdint>

struct UploadResult {
  int code;            // 마지막 HTTP 코드 (음수는 HTTPClient 네트워크 오류)
  int tries;           // 시도 횟수 (1~4)
  uint32_t send_ms;    // 첫 시도부터 끝까지 (재시도 대기 포함)
  char event_id[72];   // 202/200 응답의 event_id, 없으면 빈 문자열
};

// captured_at: 촬영 순간의 UTC ISO 8601 (NTP 미동기화면 nullptr → X-Captured-At 생략)
// score < 0 이면 X-Detector-Score 생략. 재시도 때 capture_id·captured_at은 그대로 쓴다.
UploadResult uploader_send(const uint8_t *jpg, size_t len, const char *capture_id, const char *captured_at,
                           const char *trigger, float score);
