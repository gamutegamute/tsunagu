#pragma once
#include <cstdint>
inline uint32_t esp_random() {
  static uint32_t state = 12345;
  return state = state * 1664525u + 1013904223u;
}
