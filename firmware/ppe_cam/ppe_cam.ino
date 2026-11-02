// PPE Edge Guard 카메라 펌웨어 (XIAO ESP32S3 Sense)
// 사람이 감지되면 고해상도 JPEG을 찍어 게이트웨이 ingest로 보낸다 (docs/interfaces.md ①).
// 설계: firmware/docs/2026-11-02-firmware-capture-design.md
// 시리얼 명령: c = 지금 촬영·전송, r = 마지막 사진을 같은 X-Capture-Id로 재전송(중복 200 확인)
#include "settings.h"

#include <WiFi.h>
#include <esp_heap_caps.h>
#include <esp_random.h>

#include "camera.h"
#include "detector.h"
#include "net.h"
#include "proto.h"
#include "uploader.h"

static uint32_t last_status_ms = 0;
static uint32_t cooldown_until_ms = 0;
static uint32_t boot_rand = 0;
static uint32_t seq = 0;
static bool camera_ready = false;

// 'r' 재전송용 마지막 사진 (PSRAM)
static uint8_t *last_jpg = nullptr;
static size_t last_len = 0;
static size_t last_cap = 0;
static char last_capture_id[24] = "";
static char last_trigger[8] = "";

static void keep_last(const uint8_t *jpg, size_t len, const char *capture_id, const char *trigger) {
  if (len > last_cap) {
    free(last_jpg);
    last_jpg = (uint8_t *)ps_malloc(len);
    last_cap = last_jpg ? len : 0;
  }
  if (!last_jpg) {
    last_len = 0;
    return;
  }
  memcpy(last_jpg, jpg, len);
  last_len = len;
  strncpy(last_capture_id, capture_id, sizeof last_capture_id - 1);
  strncpy(last_trigger, trigger, sizeof last_trigger - 1);
}

static void print_summary(const char *id, const char *trig, size_t len, int w, int h, uint32_t cap_ms,
                          const UploadResult &u) {
  Serial.printf("[cap] id=%s trig=%s size=%uB %dx%d cap=%lums send=%lums code=%d event=%s tries=%d\n", id, trig,
                (unsigned)len, w, h, (unsigned long)cap_ms, (unsigned long)u.send_ms, u.code,
                u.event_id[0] ? u.event_id : "-", u.tries);
}

static void capture_and_send(const DetectResult &d) {
  if (!camera_ready) {
    Serial.println("[cap] skip: camera not ready");
    return;
  }
  if (!net_connected()) {
    Serial.println("[cap] skip: no wifi");
    return;
  }
  uint32_t cap_ms = 0;
  camera_fb_t *fb = camera_capture_hires(&cap_ms);
  if (!fb) return;
  if (!proto_jpeg_ok(fb->buf, fb->len)) {
    Serial.printf("[cap] skip: bad jpeg (len=%u)\n", (unsigned)fb->len);
    camera_release_hires(fb);
    cooldown_until_ms = millis() + COOLDOWN_MS;
    return;
  }
  char capture_id[24];
  proto_capture_id(capture_id, sizeof capture_id, boot_rand, ++seq);
  keep_last(fb->buf, fb->len, capture_id, d.trigger);
  UploadResult u = uploader_send(fb->buf, fb->len, capture_id, d.trigger, d.score);
  print_summary(capture_id, d.trigger, fb->len, fb->width, fb->height, cap_ms, u);
  camera_release_hires(fb);
  cooldown_until_ms = millis() + COOLDOWN_MS;
}

static void resend_last() {
  if (last_len == 0) {
    Serial.println("[cap] nothing to resend");
    return;
  }
  if (!net_connected()) {
    Serial.println("[cap] skip: no wifi");
    return;
  }
  UploadResult u = uploader_send(last_jpg, last_len, last_capture_id, last_trigger, -1.0f);
  print_summary(last_capture_id, last_trigger, last_len, 0, 0, 0, u);
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // PC가 시리얼을 안 읽어도 출력에서 막히지 않게
  delay(500);
  boot_rand = esp_random();
  Serial.printf("\n[boot] ppe_cam fw=%s device=%s psram=%u\n", FIRMWARE_VERSION, DEVICE_ID,
                (unsigned)heap_caps_get_total_size(MALLOC_CAP_SPIRAM));
  if (!proto_valid_device_id(DEVICE_ID)) {
    Serial.println("[boot] DEVICE_ID 형식 오류 (^[a-z0-9-]{3,32}$) — ingest가 400을 돌려준다");
  }
  camera_ready = camera_begin();
  if (!camera_ready) Serial.println("[boot] camera init failed — 촬영 불가");
  net_begin();
  detector_begin();
  Serial.println("[boot] ready: c=capture, r=resend last");
}

void loop() {
  net_loop();

  // F2에서는 여기서 camera_grab_detect()로 감지 프레임을 얻어 넘긴다
  DetectResult d = detector_poll(nullptr);
  if (d.triggered) {
    if ((int32_t)(millis() - cooldown_until_ms) < 0) {
      Serial.printf("[cap] skip: cooldown %lums left\n", (unsigned long)(cooldown_until_ms - millis()));
    } else {
      capture_and_send(d);
    }
  }

  // detector가 소비하지 않은 시리얼 명령. 'c'는 읽지 않고 남겨 다음 loop에서 detector가 읽게 한다
  while (Serial.available() && Serial.peek() != 'c') {
    int ch = Serial.read();
    if (ch == 'r') resend_last();  // 줄바꿈 등 나머지 문자는 버림
  }

  if (millis() - last_status_ms >= 10000) {
    last_status_ms = millis();
    char ts[32];
    bool synced = net_time_iso(ts, sizeof ts);
    Serial.printf("[net] wifi=%s rssi=%d time=%s\n", net_connected() ? "connected" : "disconnected",
                  net_connected() ? WiFi.RSSI() : 0, synced ? ts : "unsynced");
  }
  delay(10);
}
