// 감지 인터페이스. F1은 detector_manual.cpp(시리얼 c·타이머), F2에서 detector_ei.cpp로 바꾼다.
#pragma once
#include <esp_camera.h>

struct DetectResult {
  bool triggered;
  const char *trigger;  // X-Trigger 값: "serial" / "timer" / "person"
  float score;          // X-Detector-Score, 음수면 헤더 생략
};

void detector_begin();
// frame: 감지용 프레임(DETECT_FRAMESIZE JPEG). 임시 감지는 쓰지 않으므로 nullptr 가능
DetectResult detector_poll(camera_fb_t *frame);
