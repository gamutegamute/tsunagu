#pragma once
// NVS のスタブ。保存先は static(別の Store からも見える = 再起動のあとも残る)。失敗は、テストが注入する。
#include <map>
#include <string>
#include <vector>

#include "Arduino.h"

struct FakeNvs {
  std::map<std::string, std::vector<uint8_t>> data;
  bool failRemove = false;                   // remove() が false を返し、キーが残る
  bool removeFalseButErases = false;         // remove() は false を返すが、キーは消える(キーが元から無い場合など)
  bool removeTrueButKeyRemains = false;      // remove() は true を返すが、キーが残る
  std::string failPutULongKey;               // この名前の putULong() は 0 を返す(保存されない)
  static FakeNvs &get() {
    static FakeNvs nvs;
    return nvs;
  }
};

class Preferences {
 public:
  bool begin(const char *, bool) { return true; }
  bool isKey(const char *key) { return FakeNvs::get().data.count(key) > 0; }
  bool remove(const char *key) {
    FakeNvs &nvs = FakeNvs::get();
    if (nvs.failRemove) return false;
    if (nvs.removeTrueButKeyRemains) return true;
    const bool existed = nvs.data.erase(key) > 0;
    return nvs.removeFalseButErases ? false : existed;  // 実機の remove() も、キーが無いときは false
  }
  size_t putULong(const char *key, uint32_t value) {
    if (FakeNvs::get().failPutULongKey == key) return 0;
    const uint8_t *p = reinterpret_cast<const uint8_t *>(&value);
    FakeNvs::get().data[key] = std::vector<uint8_t>(p, p + sizeof(value));
    return sizeof(value);
  }
  uint32_t getULong(const char *key, uint32_t fallback) {
    auto it = FakeNvs::get().data.find(key);
    if (it == FakeNvs::get().data.end()) return fallback;
    uint32_t value = 0;
    std::memcpy(&value, it->second.data(), sizeof(value));
    return value;
  }
  size_t putString(const char *key, const char *value) {
    FakeNvs::get().data[key] = std::vector<uint8_t>(value, value + std::strlen(value));
    return std::strlen(value);
  }
  size_t getString(const char *key, char *out, size_t size) {
    auto &bytes = FakeNvs::get().data[key];
    const size_t n = bytes.size() < size - 1 ? bytes.size() : size - 1;
    std::memcpy(out, bytes.data(), n);
    out[n] = '\0';
    return n;
  }
  size_t putBytes(const char *key, const void *value, size_t length) {
    const uint8_t *p = static_cast<const uint8_t *>(value);
    FakeNvs::get().data[key] = std::vector<uint8_t>(p, p + length);
    return length;
  }
  size_t getBytesLength(const char *key) { return FakeNvs::get().data[key].size(); }
  size_t getBytes(const char *key, void *out, size_t length) {
    auto &bytes = FakeNvs::get().data[key];
    const size_t n = bytes.size() < length ? bytes.size() : length;
    std::memcpy(out, bytes.data(), n);
    return n;
  }
};
