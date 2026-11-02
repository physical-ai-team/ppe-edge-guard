#include "net.h"

#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

#include "settings.h"
#include "proto.h"

static uint32_t last_retry_ms = 0;
static bool was_connected = false;

void net_begin() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[net] connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();
  was_connected = WiFi.status() == WL_CONNECTED;
  if (was_connected) {
    Serial.printf("[net] wifi=connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("[net] wifi=disconnected (will retry)");
  }
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC
}

void net_loop() {
  bool now = WiFi.status() == WL_CONNECTED;
  if (now != was_connected) {
    was_connected = now;
    if (now) {
      Serial.printf("[net] wifi=connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
      Serial.println("[net] wifi=disconnected");
    }
  }
  if (!now && millis() - last_retry_ms >= WIFI_RETRY_MS) {
    last_retry_ms = millis();
    WiFi.reconnect();
  }
}

bool net_connected() { return WiFi.status() == WL_CONNECTED; }

bool net_time_iso(char *out, size_t n) { return proto_iso8601_utc(time(nullptr), out, n); }
