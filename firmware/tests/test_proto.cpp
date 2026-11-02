// proto 모듈 단위 시험 (PC g++). 실행: powershell -File firmware/tests/run_tests.ps1
#include <cstdio>
#include <cstring>
#include <string>

#include "proto.h"

static int failures = 0;
#define CHECK(cond)                                                    \
  do {                                                                 \
    if (!(cond)) {                                                     \
      std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);      \
      failures++;                                                      \
    }                                                                  \
  } while (0)

static void test_device_id() {
  CHECK(proto_valid_device_id("cam-01"));
  CHECK(proto_valid_device_id("cam-minsung"));
  CHECK(!proto_valid_device_id("ab"));
  CHECK(!proto_valid_device_id("Cam-01"));
  CHECK(!proto_valid_device_id("cam_01"));
  CHECK(!proto_valid_device_id(std::string(33, 'a').c_str()));
  CHECK(proto_valid_device_id(std::string(32, 'a').c_str()));
}

static void test_capture_id() {
  char buf[32];
  proto_capture_id(buf, sizeof buf, 0x5e1a9c02u, 42);
  CHECK(std::strcmp(buf, "5e1a9c02-000042") == 0);
}

static void test_iso8601() {
  char buf[32];
  CHECK(proto_iso8601_utc(1793597472, buf, sizeof buf));
  CHECK(std::strcmp(buf, "2026-11-02T05:31:12Z") == 0);
  CHECK(proto_iso8601_utc(1704067200, buf, sizeof buf));
  CHECK(std::strcmp(buf, "2024-01-01T00:00:00Z") == 0);
  CHECK(!proto_iso8601_utc(0, buf, sizeof buf));
  CHECK(!proto_iso8601_utc(1704067199, buf, sizeof buf));
}

static void test_classify() {
  CHECK(proto_classify(202) == SendAction::Success);
  CHECK(proto_classify(200) == SendAction::Success);
  CHECK(proto_classify(400) == SendAction::Fatal);
  CHECK(proto_classify(401) == SendAction::Fatal);
  CHECK(proto_classify(413) == SendAction::Fatal);
  CHECK(proto_classify(404) == SendAction::Fatal);
  CHECK(proto_classify(503) == SendAction::Retry);
  CHECK(proto_classify(500) == SendAction::Retry);
  CHECK(proto_classify(-1) == SendAction::Retry);   // HTTPC_ERROR_CONNECTION_REFUSED
  CHECK(proto_classify(-11) == SendAction::Retry);  // HTTPC_ERROR_READ_TIMEOUT
  CHECK(proto_classify(302) == SendAction::Fatal);
}

static void test_retry_delay() {
  CHECK(proto_retry_delay_ms(1, -1) == 1000);
  CHECK(proto_retry_delay_ms(2, -1) == 2000);
  CHECK(proto_retry_delay_ms(3, -1) == 4000);
  CHECK(proto_retry_delay_ms(1, 2) == 2000);
  CHECK(proto_retry_delay_ms(1, 30) == 4000);
  CHECK(proto_retry_delay_ms(2, 0) == 0);
}

static void test_extract_event_id() {
  char buf[72];
  CHECK(proto_extract_event_id(
      "{\"event_id\": \"cam-01_20261102T053112Z_a1b2c3\", \"status\": \"received\"}", buf, sizeof buf));
  CHECK(std::strcmp(buf, "cam-01_20261102T053112Z_a1b2c3") == 0);
  CHECK(proto_extract_event_id("{\"event_id\":\"x-1\",\"status\":\"duplicate\"}", buf, sizeof buf));
  CHECK(std::strcmp(buf, "x-1") == 0);
  CHECK(!proto_extract_event_id("{\"error\":\"invalid_token\"}", buf, sizeof buf));
  char small[8];
  CHECK(!proto_extract_event_id("{\"event_id\": \"cam-01_20261102T053112Z_a1b2c3\"}", small, sizeof small));
}

static void test_jpeg_ok() {
  const uint8_t jpg[] = {0xFF, 0xD8, 0xFF, 0xE0};
  const uint8_t png[] = {0x89, 0x50, 0x4E, 0x47};
  CHECK(proto_jpeg_ok(jpg, sizeof jpg));
  CHECK(!proto_jpeg_ok(png, sizeof png));
  CHECK(!proto_jpeg_ok(jpg, 0));
  CHECK(!proto_jpeg_ok(jpg, 1));
  CHECK(proto_jpeg_ok(jpg, 2097152));   // 길이만 인자로 검사 (버퍼는 앞 2바이트만 읽음)
  CHECK(!proto_jpeg_ok(jpg, 2097153));
  CHECK(!proto_jpeg_ok(nullptr, 4));
}

int main() {
  test_device_id();
  test_capture_id();
  test_iso8601();
  test_classify();
  test_retry_delay();
  test_extract_event_id();
  test_jpeg_ok();
  if (failures == 0) std::printf("ALL PASS\n");
  else std::printf("%d FAILED\n", failures);
  return failures == 0 ? 0 : 1;
}
