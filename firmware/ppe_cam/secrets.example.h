// 이 파일을 같은 폴더에 secrets.h로 복사해서 값을 채운다. secrets.h는 커밋하지 않는다(gitignore).
#pragma once

#define WIFI_SSID "your-ssid"
#define WIFI_PASSWORD "your-password"

// 게이트웨이(ingest) 주소. 노트북 시험이면 ipconfig로 본 노트북 IP, 시연이면 Pi IP
#define GATEWAY_HOST "192.168.0.10"
#define GATEWAY_PORT 8000

// gateway/.env 의 DEVICE_TOKEN과 같은 값 (단독 시험은 dev-token)
#define DEVICE_TOKEN "dev-token"

// 개인 시험용 장치 이름 (선택). 정하지 않으면 config.h의 cam-01
// #define DEVICE_ID "cam-minsung"
