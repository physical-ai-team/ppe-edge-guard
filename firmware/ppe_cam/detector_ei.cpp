// F2 사람 감지: Edge Impulse FOMO. config.h의 DETECTOR_EI=1일 때만 컴파일된다.
// 감지 프레임(DETECT_FRAMESIZE JPEG) → RGB888 → 모델 입력 크기로 축소 → run_classifier → person 점수
// 시리얼 'c'(serial)도 그대로 받는다 — 실기 시험용.
#include "settings.h"

#if DETECTOR_EI

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <img_converters.h>

#include EI_HEADER

#include "detector.h"

static uint8_t *rgb_full = nullptr;   // DETECT 해상도 RGB888 (PSRAM)
static uint8_t *rgb_model = nullptr;  // 모델 입력 크기 RGB888
static uint32_t last_infer_ms = 0;
static int hits = 0;

// EI SDK 기본 ei_calloc은 정렬이 보장되지 않아 코어 3.x에서 힙이 깨진다(zero-touch 교훈).
// SDK의 weak 정의를 16바이트 정렬 할당으로 덮어쓴다.
void *ei_malloc(size_t size) { return heap_caps_aligned_alloc(16, size, MALLOC_CAP_8BIT); }
void *ei_calloc(size_t nitems, size_t size) {
  return heap_caps_aligned_calloc(16, nitems, size, MALLOC_CAP_8BIT);
}
void ei_free(void *ptr) { heap_caps_free(ptr); }

static int get_signal_data(size_t offset, size_t length, float *out) {
  const uint8_t *p = rgb_model + offset * 3;
  for (size_t i = 0; i < length; i++, p += 3) {
    out[i] = (float)((p[0] << 16) | (p[1] << 8) | p[2]);  // fmt2rgb888 출력은 RGB 순서. 뒤집지 않는다
  }
  return 0;
}

void detector_begin() {
  rgb_model = (uint8_t *)heap_caps_malloc(EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3,
                                          MALLOC_CAP_8BIT);
  Serial.printf("[det] edge impulse %dx%d, threshold=%.2f, interval=%dms, hits=%d\n",
                EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT, (double)PERSON_THRESHOLD,
                DETECT_INTERVAL_MS, DETECT_CONSECUTIVE);
}

bool detector_wants_frame() { return millis() - last_infer_ms >= DETECT_INTERVAL_MS; }

// 사람 점수(0~1). 실패하면 음수
static float infer_person(camera_fb_t *frame) {
  size_t full_len = (size_t)frame->width * frame->height * 3;
  static size_t full_cap = 0;
  if (full_cap < full_len) {
    heap_caps_free(rgb_full);
    rgb_full = (uint8_t *)heap_caps_malloc(full_len, MALLOC_CAP_SPIRAM);
    full_cap = rgb_full ? full_len : 0;
  }
  if (!rgb_full || !rgb_model) return -1.0f;
  if (!fmt2rgb888(frame->buf, frame->len, frame->format, rgb_full)) return -1.0f;

  ei::image::processing::crop_and_interpolate_rgb888(rgb_full, frame->width, frame->height, rgb_model,
                                                     EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);

  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &get_signal_data;
  ei_impulse_result_t result = {};
  if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) return -1.0f;

  float best = 0.0f;
  for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    const auto &bb = result.bounding_boxes[i];
    if (bb.value > 0 && strcmp(bb.label, "person") == 0 && bb.value > best) best = bb.value;
  }
#if DETECT_DEBUG
  Serial.printf("[det] person=%.2f boxes=%u dsp=%dms nn=%dms\n", (double)best,
                (unsigned)result.bounding_boxes_count, result.timing.dsp, result.timing.classification);
#endif
  return best;
}

DetectResult detector_poll(camera_fb_t *frame) {
  if (Serial.available() && Serial.peek() == 'c') {
    Serial.read();
    return {true, "serial", -1.0f};
  }
  if (!frame) return {false, nullptr, -1.0f};
  last_infer_ms = millis();
  float score = infer_person(frame);
  if (score < 0) {
    Serial.println("[det] inference failed");
    return {false, nullptr, -1.0f};
  }
  hits = score >= PERSON_THRESHOLD ? hits + 1 : 0;
  if (hits >= DETECT_CONSECUTIVE) {
    hits = 0;
    return {true, "person", score};
  }
  return {false, nullptr, -1.0f};
}

#endif  // DETECTOR_EI
