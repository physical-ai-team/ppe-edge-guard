// F1 임시 감지: 시리얼 'c' → serial, DETECTOR_TIMER_MS > 0 이면 주기마다 timer
#include <Arduino.h>

#include "detector.h"
#include "settings.h"

static uint32_t last_timer_ms = 0;

void detector_begin() { last_timer_ms = millis(); }

DetectResult detector_poll(camera_fb_t *frame) {
  (void)frame;
  // 'c'만 여기서 소비하고, 다른 시리얼 명령('r' 등)은 .ino가 읽도록 남겨 둔다
  if (Serial.available() && Serial.peek() == 'c') {
    Serial.read();
    return {true, "serial", -1.0f};
  }
#if DETECTOR_TIMER_MS > 0
  if (millis() - last_timer_ms >= DETECTOR_TIMER_MS) {
    last_timer_ms = millis();
    return {true, "timer", -1.0f};
  }
#endif
  return {false, nullptr, -1.0f};
}
