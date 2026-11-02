// 공개 설정값 (커밋함). 개인 값은 secrets.h에서 같은 이름으로 먼저 #define하면 덮어쓴다.
// 기준: firmware/docs/2026-11-02-firmware-capture-design.md 4.1절, docs/interfaces.md ①
#pragma once

#ifndef DEVICE_ID
#define DEVICE_ID "cam-01"  // ^[a-z0-9-]{3,32}$
#endif

#ifndef CAPTURE_FRAMESIZE
#define CAPTURE_FRAMESIZE FRAMESIZE_SXGA  // 전송용 1280x1024
#endif

#ifndef CAPTURE_JPEG_QUALITY
#define CAPTURE_JPEG_QUALITY 12  // 낮을수록 고화질. 2MB 넘으면 413
#endif

#ifndef DETECT_FRAMESIZE
#define DETECT_FRAMESIZE FRAMESIZE_QVGA  // 평소 감지용 320x240
#endif

#ifndef CAPTURE_DISCARD_FRAMES
#define CAPTURE_DISCARD_FRAMES 2  // 해상도 전환 직후 버리는 장 수
#endif

#ifndef COOLDOWN_MS
#define COOLDOWN_MS 5000  // 전송이 끝난 뒤 다음 촬영까지 (성공·실패 모두)
#endif

#ifndef DETECTOR_TIMER_MS
#define DETECTOR_TIMER_MS 0  // 0이면 꺼짐. 예: 15000 → 15초마다 자동 촬영 (X-Trigger: timer)
#endif

// F2 사람 감지 (Edge Impulse). 1이면 detector_ei(EI 라이브러리 설치 필요, firmware/README.md),
// 0이면 detector_manual(시리얼·타이머, 라이브러리 없이 빌드)
#ifndef DETECTOR_EI
#define DETECTOR_EI 1
#endif

#ifndef EI_HEADER
#define EI_HEADER <ppe-person-fomo_inferencing.h>  // EI에서 내보낸 Arduino 라이브러리 헤더
#endif

#ifndef PERSON_THRESHOLD
#define PERSON_THRESHOLD 0.3f  // FOMO person 점수 기준(모델 min_score도 이 값으로 바꾼다). 놓치는 것보다 오탐이 낫다(Pi가 거름)
#endif

#ifndef DETECT_INTERVAL_MS
#define DETECT_INTERVAL_MS 200  // 감지 프레임 추론 간격
#endif

#ifndef DETECT_CONSECUTIVE
#define DETECT_CONSECUTIVE 2  // 연속 몇 번 넘어야 촬영할지 (한 프레임 오탐 거르기)
#endif

#ifndef DETECT_DEBUG
#define DETECT_DEBUG 0  // 1이면 추론마다 점수·시간 출력
#endif

#ifndef HTTP_TIMEOUT_MS
#define HTTP_TIMEOUT_MS 10000  // 계약값
#endif

#ifndef WIFI_RETRY_MS
#define WIFI_RETRY_MS 15000  // 끊겼을 때 재연결 시도 간격 (한 번 시도에 몇 초 걸리므로 너무 짧으면 시도가 계속 끊긴다)
#endif

#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "0.2.0"  // 0.2: F2 사람 감지
#endif
