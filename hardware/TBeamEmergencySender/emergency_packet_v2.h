#pragma once

// Emergency Packet v2 の生成と署名。仕様の正は docs/emergency-packet-v2.md。
//
// v2|device_id|key_id|install_id|sequence|reported_at|shelter_code|people_count|water_stock|status|request_code|hmac
//
// hmac = HMAC-SHA256(端末の鍵, "v2|" から request_code まで) の先頭16バイトを小文字16進32文字にしたもの。
// 鍵・hmac・sequence はブラウザへ渡さない。

#include <Arduino.h>
#include <mbedtls/md.h>

#include "device_settings.h"

namespace emergency_packet_v2 {

constexpr size_t HMAC_BYTES = 16;
constexpr size_t HMAC_HEX_LENGTH = HMAC_BYTES * 2;
constexpr uint32_t MAX_REPORT_VALUE = 1000000UL;
// 2024-01-01T00:00:00Z より前の reported_at は、端末(スマートフォン)の時計が合っていないとみなして拒否する。
constexpr uint32_t MIN_REPORTED_AT = 1704067200UL;

const char *const ALLOWED_STATUSES[] = {"NORMAL", "WARNING", "ALERT", "CRITICAL"};
const char *const ALLOWED_REQUEST_CODES[] = {
    "REQ_WATER", "REQ_MEDICAL", "REQ_FOOD", "REQ_RESCUE", "REQ_CONFIRM", "NONE"};

// 各フィールドの最大長から求めたPacketの最大長。
//   "v2" 2 + device_id 5 + key_id 2 + install_id 16 + sequence 8 + reported_at 10 + shelter_code 12
//   + people_count 7 + water_stock 7 + status 8 ("CRITICAL") + request_code 11 ("REQ_MEDICAL") + hmac 32
//   + 区切り 11
constexpr size_t MAX_PACKET_LENGTH = 2 + device_settings::DEVICE_ID_LENGTH + device_settings::KEY_ID_LENGTH +
                                     device_settings::INSTALL_ID_LENGTH + 8 + 10 +
                                     device_settings::MAX_SHELTER_CODE_LENGTH + 7 + 7 + 8 + 11 + HMAC_HEX_LENGTH +
                                     11;
static_assert(MAX_PACKET_LENGTH < 255, "Emergency Packet v2 must be shorter than 255 bytes");
constexpr size_t PACKET_BUFFER_SIZE = MAX_PACKET_LENGTH + 1;

struct Report {
  uint32_t reportedAt = 0;
  uint32_t peopleCount = 0;
  uint32_t waterStock = 0;
  const char *status = nullptr;
  const char *requestCode = nullptr;
};

inline const char *findAllowed(const String &value, const char *const allowed[], size_t count) {
  for (size_t i = 0; i < count; ++i) {
    if (value == allowed[i]) {
      return allowed[i];
    }
  }
  return nullptr;
}

inline bool parseDigits(const String &raw, size_t maxDigits, uint32_t &out) {
  if (raw.length() == 0 || raw.length() > maxDigits) {
    return false;
  }
  uint64_t value = 0;
  for (size_t i = 0; i < raw.length(); ++i) {
    if (raw[i] < '0' || raw[i] > '9') {
      return false;
    }
    value = value * 10 + static_cast<uint64_t>(raw[i] - '0');
  }
  if (value > 0xFFFFFFFFULL) {
    return false;
  }
  out = static_cast<uint32_t>(value);
  return true;
}

inline bool parseReportedAt(const String &raw, uint32_t &out) {
  return parseDigits(raw, 10, out) && out >= MIN_REPORTED_AT;
}

inline bool parseCount(const String &raw, uint32_t &out) {
  return parseDigits(raw, 7, out) && out <= MAX_REPORT_VALUE;
}

inline bool parseReport(const String &reportedAt, const String &peopleCount, const String &waterStock,
                        const String &status, const String &requestCode, Report &report) {
  report.status = findAllowed(status, ALLOWED_STATUSES, sizeof(ALLOWED_STATUSES) / sizeof(ALLOWED_STATUSES[0]));
  report.requestCode =
      findAllowed(requestCode, ALLOWED_REQUEST_CODES, sizeof(ALLOWED_REQUEST_CODES) / sizeof(ALLOWED_REQUEST_CODES[0]));
  return parseReportedAt(reportedAt, report.reportedAt) && parseCount(peopleCount, report.peopleCount) &&
         parseCount(waterStock, report.waterStock) && report.status != nullptr && report.requestCode != nullptr;
}

// HMAC-SHA256 の先頭16バイトを小文字16進32文字にする。
inline bool computeHmacHex(const uint8_t *key, size_t keyLength, const char *message, size_t messageLength,
                           char out[HMAC_HEX_LENGTH + 1]) {
  uint8_t digest[32] = {};
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (info == nullptr ||
      mbedtls_md_hmac(info, key, keyLength, reinterpret_cast<const unsigned char *>(message), messageLength,
                      digest) != 0) {
    return false;
  }
  static const char HEX_DIGITS[] = "0123456789abcdef";
  for (size_t i = 0; i < HMAC_BYTES; ++i) {
    out[i * 2] = HEX_DIGITS[digest[i] >> 4];
    out[i * 2 + 1] = HEX_DIGITS[digest[i] & 0x0F];
  }
  out[HMAC_HEX_LENGTH] = '\0';
  memset(digest, 0, sizeof(digest));
  return true;
}

// 署名対象("v2|"〜request_code)を作る。戻り値は書いた長さ(失敗時は0)。
inline size_t buildSignedPayload(const char *deviceId, const char *keyId, const char *installId, uint32_t sequence,
                                 const char *shelterCode, const Report &report, char *out, size_t outSize) {
  const int written = snprintf(out, outSize, "v2|%s|%s|%s|%08lX|%lu|%s|%lu|%lu|%s|%s", deviceId, keyId, installId,
                               static_cast<unsigned long>(sequence), static_cast<unsigned long>(report.reportedAt),
                               shelterCode, static_cast<unsigned long>(report.peopleCount),
                               static_cast<unsigned long>(report.waterStock), report.status, report.requestCode);
  if (written <= 0 || static_cast<size_t>(written) >= outSize) {
    return 0;
  }
  return static_cast<size_t>(written);
}

// 完成したPacket(署名対象 + "|" + hmac)を作る。戻り値はPacketの長さ(失敗時は0)。
inline size_t buildPacket(const device_settings::Settings &settings, uint32_t sequence, const Report &report,
                          char out[PACKET_BUFFER_SIZE]) {
  const size_t payloadLength = buildSignedPayload(settings.deviceId, settings.keyId, settings.installId, sequence,
                                                  settings.shelterCode, report, out, PACKET_BUFFER_SIZE);
  if (payloadLength == 0 || payloadLength + 1 + HMAC_HEX_LENGTH > MAX_PACKET_LENGTH) {
    return 0;
  }
  char hmacHex[HMAC_HEX_LENGTH + 1];
  if (!computeHmacHex(settings.hmacKey, settings.hmacKeyLength, out, payloadLength, hmacHex)) {
    return 0;
  }
  out[payloadLength] = '|';
  memcpy(out + payloadLength + 1, hmacHex, HMAC_HEX_LENGTH + 1);
  return payloadLength + 1 + HMAC_HEX_LENGTH;
}

#ifdef TSUNAGU_SELFTEST
// docs/emergency-packet-v2.md のテストベクトル。鍵はテスト専用のダミー値(00 01 ... 1f)。
// TSUNAGU_SELFTEST を付けたビルドにだけ入る。
inline bool runHmacSelfTest(Print &log) {
  uint8_t key[32];
  for (size_t i = 0; i < sizeof(key); ++i) {
    key[i] = static_cast<uint8_t>(i);
  }
  device_settings::Settings settings;
  strlcpy(settings.deviceId, "TB001", sizeof(settings.deviceId));
  strlcpy(settings.keyId, "01", sizeof(settings.keyId));
  strlcpy(settings.installId, "A1B2C3D4E5F60718", sizeof(settings.installId));
  strlcpy(settings.shelterCode, "AIT001", sizeof(settings.shelterCode));
  memcpy(settings.hmacKey, key, sizeof(key));
  settings.hmacKeyLength = sizeof(key);

  Report report;
  report.reportedAt = 1791234567UL;
  report.peopleCount = 170;
  report.waterStock = 18;
  report.status = "WARNING";
  report.requestCode = "REQ_WATER";

  static const char EXPECTED[] =
      "v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER|"
      "c23c0c17326995159c0cc9dfafe7fd8c";
  char packet[PACKET_BUFFER_SIZE];
  const size_t length = buildPacket(settings, 0x2A, report, packet);
  const bool ok = length == strlen(EXPECTED) && strcmp(packet, EXPECTED) == 0;
  log.println(ok ? F("[selftest] HMAC test vector: OK") : F("[selftest] HMAC test vector: NG"));
  return ok;
}
#endif

}  // namespace emergency_packet_v2
