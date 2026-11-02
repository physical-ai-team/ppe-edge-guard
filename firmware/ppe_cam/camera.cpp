#include "camera.h"

#include <Arduino.h>

#include "settings.h"

// 핀: arduino-esp32 CameraWebServer camera_pins.h 의 CAMERA_MODEL_XIAO_ESP32S3 (zero-touch에서 실기 확인)
#define CAM_PIN_XCLK  10
#define CAM_PIN_SIOD  40
#define CAM_PIN_SIOC  39
#define CAM_PIN_Y9    48
#define CAM_PIN_Y8    11
#define CAM_PIN_Y7    12
#define CAM_PIN_Y6    14
#define CAM_PIN_Y5    16
#define CAM_PIN_Y4    18
#define CAM_PIN_Y3    17
#define CAM_PIN_Y2    15
#define CAM_PIN_VSYNC 38
#define CAM_PIN_HREF  47
#define CAM_PIN_PCLK  13

static bool set_size(framesize_t size) {
  sensor_t *s = esp_camera_sensor_get();
  if (!s || s->set_framesize(s, size) != 0) {
    Serial.printf("[cam] set_framesize(%d) failed\n", (int)size);
    return false;
  }
  return true;
}

bool camera_begin() {
  camera_config_t c = {};
  c.pin_pwdn = -1;
  c.pin_reset = -1;
  c.pin_xclk = CAM_PIN_XCLK;
  c.pin_sccb_sda = CAM_PIN_SIOD;
  c.pin_sccb_scl = CAM_PIN_SIOC;
  c.pin_d7 = CAM_PIN_Y9;
  c.pin_d6 = CAM_PIN_Y8;
  c.pin_d5 = CAM_PIN_Y7;
  c.pin_d4 = CAM_PIN_Y6;
  c.pin_d3 = CAM_PIN_Y5;
  c.pin_d2 = CAM_PIN_Y4;
  c.pin_d1 = CAM_PIN_Y3;
  c.pin_d0 = CAM_PIN_Y2;
  c.pin_vsync = CAM_PIN_VSYNC;
  c.pin_href = CAM_PIN_HREF;
  c.pin_pclk = CAM_PIN_PCLK;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_0;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.pixel_format = PIXFORMAT_JPEG;
  // 버퍼를 가장 큰 해상도 기준으로 잡기 위해 CAPTURE 크기로 초기화한 뒤 DETECT로 내린다
  c.frame_size = CAPTURE_FRAMESIZE;
  c.jpeg_quality = CAPTURE_JPEG_QUALITY;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("[cam] init failed 0x%x\n", err);
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  Serial.printf("[cam] ok, sensor PID=0x%x\n", s ? s->id.PID : 0);
  return set_size(DETECT_FRAMESIZE);
}

camera_fb_t *camera_capture_hires(uint32_t *elapsed_ms) {
  uint32_t start = millis();
  if (!set_size(CAPTURE_FRAMESIZE)) return nullptr;
  for (int i = 0; i < CAPTURE_DISCARD_FRAMES; i++) {
    camera_fb_t *old = esp_camera_fb_get();
    if (old) esp_camera_fb_return(old);
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (elapsed_ms) *elapsed_ms = millis() - start;
  if (!fb) {
    Serial.println("[cam] capture failed");
    set_size(DETECT_FRAMESIZE);
    return nullptr;
  }
  return fb;
}

void camera_release_hires(camera_fb_t *fb) {
  if (fb) esp_camera_fb_return(fb);
  set_size(DETECT_FRAMESIZE);
}

camera_fb_t *camera_grab_detect() { return esp_camera_fb_get(); }

void camera_return(camera_fb_t *fb) {
  if (fb) esp_camera_fb_return(fb);
}
