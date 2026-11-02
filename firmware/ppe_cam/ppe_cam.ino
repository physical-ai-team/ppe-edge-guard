// PPE Edge Guard 카메라 펌웨어 (XIAO ESP32S3 Sense)
// 사람이 감지되면 고해상도 JPEG을 찍어 게이트웨이 ingest로 보낸다 (docs/interfaces.md ①).
// 설계: firmware/docs/2026-11-02-firmware-capture-design.md
#include "settings.h"

#include <WiFi.h>
#include <esp_heap_caps.h>

#include "net.h"
#include "proto.h"

static uint32_t last_status_ms = 0;

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // PC가 시리얼을 안 읽어도 출력에서 막히지 않게
  delay(500);
  Serial.printf("\n[boot] ppe_cam fw=%s device=%s psram=%u\n", FIRMWARE_VERSION, DEVICE_ID,
                (unsigned)heap_caps_get_total_size(MALLOC_CAP_SPIRAM));
  if (!proto_valid_device_id(DEVICE_ID)) {
    Serial.println("[boot] DEVICE_ID 형식 오류 (^[a-z0-9-]{3,32}$) — ingest가 400을 돌려준다");
  }
  net_begin();
}

void loop() {
  net_loop();
  if (millis() - last_status_ms >= 10000) {
    last_status_ms = millis();
    char ts[32];
    bool synced = net_time_iso(ts, sizeof ts);
    Serial.printf("[net] wifi=%s rssi=%d time=%s\n", net_connected() ? "connected" : "disconnected",
                  net_connected() ? WiFi.RSSI() : 0, synced ? ts : "unsynced");
  }
  delay(10);
}
