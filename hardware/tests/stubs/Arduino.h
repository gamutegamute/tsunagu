#pragma once
// PC上でファームのヘッダーを試すための最小のスタブ(実機の Arduino ではない)。
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

inline size_t strlcpy(char *dst, const char *src, size_t size) {
  const size_t length = std::strlen(src);
  if (size > 0) {
    const size_t n = length >= size ? size - 1 : length;
    std::memcpy(dst, src, n);
    dst[n] = '\0';
  }
  return length;
}
