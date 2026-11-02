// 모든 소스가 설정을 읽는 한 곳: secrets.h(개인 값, 먼저) → config.h(기본값)
#pragma once
#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "secrets.example.h를 secrets.h로 복사하세요"
#endif
#include "config.h"
