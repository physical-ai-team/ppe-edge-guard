// 감지 인터페이스. config.h의 DETECTOR_EI로 detector_manual.cpp(시리얼 c·타이머) / detector_ei.cpp(Edge Impulse) 중 하나가 컴파일된다.
#pragma once
#include <esp_camera.h>

struct DetectResult {
  bool triggered;
  const char *trigger;  // X-Trigger 값: "serial" / "timer" / "person"
  float score;          // X-Detector-Score, 음수면 헤더 생략
};

void detector_begin();
// 이번 loop에 감지 프레임이 필요한지. true일 때만 .ino가 camera_grab_detect()로 프레임을 얻어 넘긴다
bool detector_wants_frame();
// frame: 감지용 프레임(DETECT_FRAMESIZE JPEG). 필요 없을 때는 nullptr
DetectResult detector_poll(camera_fb_t *frame);
