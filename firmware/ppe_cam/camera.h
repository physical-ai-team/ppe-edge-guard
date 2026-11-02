// 카메라: JPEG 모드 하나로 평소 DETECT_FRAMESIZE(QVGA), 촬영 때만 CAPTURE_FRAMESIZE(SXGA)
#pragma once
#include <cstdint>
#include <esp_camera.h>

bool camera_begin();

// SXGA로 바꿔 CAPTURE_DISCARD_FRAMES장 버린 뒤 한 장. 실패하면 nullptr(해상도는 DETECT로 복귀).
// 성공하면 반드시 camera_release_hires()로 반납한다.
camera_fb_t *camera_capture_hires(uint32_t *elapsed_ms);
void camera_release_hires(camera_fb_t *fb);  // 반납 후 DETECT 해상도로 복귀

// F2(Edge Impulse)용 감지 프레임. F1에서는 쓰지 않는다.
camera_fb_t *camera_grab_detect();
void camera_return(camera_fb_t *fb);
