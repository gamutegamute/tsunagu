#pragma once

// 端末ごとの設定をNVS(Preferences)に保存する。
//
// 鍵とWi-Fiのパスワードは、ソースにデフォルト値を持たない。USBシリアルの SET コマンドで書き込む。
// 鍵・パスワードの値は、ログ・シリアルに出さないこと(設定済みかどうかだけを表示する)。
// 書き込み時に「Erase All Flash」を選ぶと、NVSごと消える(docs/tbeam-provisioning.md)。

#include <Arduino.h>
#include <Preferences.h>
#include <esp_random.h>

namespace device_settings {

constexpr char NVS_NAMESPACE[] = "tsunagu";
constexpr char KEY_DEVICE_ID[] = "device_id";
constexpr char KEY_KEY_ID[] = "key_id";
constexpr char KEY_HMAC_KEY[] = "hmac_key";
constexpr char KEY_INSTALL_ID[] = "install_id";
constexpr char KEY_SEQUENCE[] = "sequence";
constexpr char KEY_SHELTER_CODE[] = "shelter_code";
constexpr char KEY_WIFI_PASS[] = "wifi_pass";

constexpr size_t DEVICE_ID_LENGTH = 5;
constexpr size_t KEY_ID_LENGTH = 2;
constexpr size_t INSTALL_ID_LENGTH = 16;
// 鍵は機器ごとの32バイトの乱数(16進で64文字)。サーバーの端末台帳も32バイト以外をエラーにするので、
// 長さの違う鍵は保存も使用もしない。
constexpr size_t HMAC_KEY_BYTES = 32;
constexpr size_t MIN_SHELTER_CODE_LENGTH = 3;
constexpr size_t MAX_SHELTER_CODE_LENGTH = 12;
constexpr size_t MIN_WIFI_PASS_LENGTH = 8;
constexpr size_t MAX_WIFI_PASS_LENGTH = 63;
// 次に使うsequenceがこの値になったら、それ以上は送らない(NEWINSTALL が必要)。
constexpr uint32_t SEQUENCE_EXHAUSTED = 0xFFFFFFFFUL;

struct Settings {
  char deviceId[DEVICE_ID_LENGTH + 1] = "";
  char keyId[KEY_ID_LENGTH + 1] = "";
  uint8_t hmacKey[HMAC_KEY_BYTES] = {};
  size_t hmacKeyLength = 0;
  char installId[INSTALL_ID_LENGTH + 1] = "";
  uint32_t nextSequence = 0;
  char shelterCode[MAX_SHELTER_CODE_LENGTH + 1] = "";
  char wifiPass[MAX_WIFI_PASS_LENGTH + 1] = "";
};

inline bool isUpperAlnum(char c) {
  return (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

inline bool isUpperHex(char c) {
  return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F');
}

inline bool isValidDeviceId(const char *value) {
  if (strlen(value) != DEVICE_ID_LENGTH) {
    return false;
  }
  for (size_t i = 0; i < DEVICE_ID_LENGTH; ++i) {
    if (!isUpperAlnum(value[i])) {
      return false;
    }
  }
  return true;
}

inline bool isUpperHexString(const char *value, size_t length) {
  if (strlen(value) != length) {
    return false;
  }
  for (size_t i = 0; i < length; ++i) {
    if (!isUpperHex(value[i])) {
      return false;
    }
  }
  return true;
}

inline bool isValidKeyId(const char *value) {
  return isUpperHexString(value, KEY_ID_LENGTH);
}

inline bool isValidInstallId(const char *value) {
  return isUpperHexString(value, INSTALL_ID_LENGTH);
}

inline bool isValidShelterCode(const char *value) {
  const size_t length = strlen(value);
  if (length < MIN_SHELTER_CODE_LENGTH || length > MAX_SHELTER_CODE_LENGTH) {
    return false;
  }
  for (size_t i = 0; i < length; ++i) {
    if (!isUpperAlnum(value[i]) && value[i] != '_' && value[i] != '-') {
      return false;
    }
  }
  return true;
}

inline bool isValidWifiPass(const char *value) {
  const size_t length = strlen(value);
  if (length < MIN_WIFI_PASS_LENGTH || length > MAX_WIFI_PASS_LENGTH) {
    return false;
  }
  for (size_t i = 0; i < length; ++i) {
    if (value[i] < 0x20 || value[i] > 0x7E) {
      return false;
    }
  }
  return true;
}

inline int hexNibble(char c) {
  if (c >= '0' && c <= '9') {
    return c - '0';
  }
  if (c >= 'a' && c <= 'f') {
    return c - 'a' + 10;
  }
  if (c >= 'A' && c <= 'F') {
    return c - 'A' + 10;
  }
  return -1;
}

// 鍵の16進文字列(64文字 = 32バイト)をバイト列にする。大文字・小文字のどちらも受け付ける。
inline bool parseHmacKeyHex(const char *hex, uint8_t *out, size_t &outLength) {
  const size_t hexLength = strlen(hex);
  if (hexLength != HMAC_KEY_BYTES * 2) {
    return false;
  }
  const size_t byteLength = HMAC_KEY_BYTES;
  for (size_t i = 0; i < byteLength; ++i) {
    const int high = hexNibble(hex[i * 2]);
    const int low = hexNibble(hex[i * 2 + 1]);
    if (high < 0 || low < 0) {
      memset(out, 0, HMAC_KEY_BYTES);
      return false;
    }
    out[i] = static_cast<uint8_t>((high << 4) | low);
  }
  outLength = byteLength;
  return true;
}

// 鍵の状態。SHOW と起動時のログには、この状態だけを出す(長さの値や鍵の中身は出さない)。
enum class HmacKeyState {
  NotSet,
  InvalidLength,  // NVS に鍵はあるが32バイトではない(旧ファームで保存した鍵など)。送信しない
  Set,
};

inline const char *hmacKeyStateLabel(HmacKeyState state) {
  switch (state) {
    case HmacKeyState::Set:
      return "set";
    case HmacKeyState::InvalidLength:
      return "invalid length";
    case HmacKeyState::NotSet:
    default:
      return "not set";
  }
}

class Store {
 public:
  bool begin() {
    ready_ = preferences_.begin(NVS_NAMESPACE, false);
    if (ready_) {
      load();
    }
    return ready_;
  }

  bool isNvsReady() const { return ready_; }
  const Settings &settings() const { return settings_; }

  bool hasDeviceId() const { return settings_.deviceId[0] != '\0'; }
  bool hasKeyId() const { return settings_.keyId[0] != '\0'; }
  // 32バイトの鍵があるときだけ true。長さの違う鍵は「鍵が無い」と同じ扱いにする。
  bool hasHmacKey() const {
    return hmacKeyState_ == HmacKeyState::Set && settings_.hmacKeyLength == HMAC_KEY_BYTES;
  }
  HmacKeyState hmacKeyState() const { return hmacKeyState_; }
  bool hasInstallId() const { return settings_.installId[0] != '\0'; }
  bool hasShelterCode() const { return settings_.shelterCode[0] != '\0'; }
  bool hasWifiPass() const { return settings_.wifiPass[0] != '\0'; }

  bool readyToSend() const {
    return ready_ && hasDeviceId() && hasKeyId() && hasHmacKey() && hasInstallId() && hasShelterCode() &&
           settings_.nextSequence != SEQUENCE_EXHAUSTED;
  }

  bool setDeviceId(const char *value) {
    if (!isValidDeviceId(value) || !putString(KEY_DEVICE_ID, value)) {
      return false;
    }
    strlcpy(settings_.deviceId, value, sizeof(settings_.deviceId));
    return true;
  }

  bool setKeyId(const char *value) {
    if (!isValidKeyId(value) || !putString(KEY_KEY_ID, value)) {
      return false;
    }
    strlcpy(settings_.keyId, value, sizeof(settings_.keyId));
    return true;
  }

  bool setHmacKeyHex(const char *hex) {
    uint8_t key[HMAC_KEY_BYTES] = {};
    size_t length = 0;
    if (!parseHmacKeyHex(hex, key, length)) {
      return false;
    }
    const bool stored = ready_ && preferences_.putBytes(KEY_HMAC_KEY, key, length) == length;
    if (stored) {
      memcpy(settings_.hmacKey, key, length);
      settings_.hmacKeyLength = length;
      hmacKeyState_ = HmacKeyState::Set;
    }
    memset(key, 0, sizeof(key));
    return stored;
  }

  bool setShelterCode(const char *value) {
    if (!isValidShelterCode(value) || !putString(KEY_SHELTER_CODE, value)) {
      return false;
    }
    strlcpy(settings_.shelterCode, value, sizeof(settings_.shelterCode));
    return true;
  }

  bool setWifiPass(const char *value) {
    if (!isValidWifiPass(value) || !putString(KEY_WIFI_PASS, value)) {
      return false;
    }
    strlcpy(settings_.wifiPass, value, sizeof(settings_.wifiPass));
    return true;
  }

  // install_id を消して sequence を0に戻す。新しい install_id は ensureInstallId() で作る。
  bool resetInstall() {
    if (!ready_) {
      return false;
    }
    preferences_.remove(KEY_INSTALL_ID);
    settings_.installId[0] = '\0';
    if (preferences_.putULong(KEY_SEQUENCE, 0) != sizeof(uint32_t)) {
      return false;
    }
    settings_.nextSequence = 0;
    return !preferences_.isKey(KEY_INSTALL_ID);
  }

  // install_id が無ければ、64ビットの乱数から作って保存する。
  // 乱数源は esp_random()。RF(Wi-Fi)が動いている間はハードウェア乱数になるので、
  // Wi-Fi(AP)の起動後にだけ呼ぶこと。
  bool ensureInstallId(bool radioFrequencyEnabled) {
    if (hasInstallId()) {
      return true;
    }
    if (!ready_ || !radioFrequencyEnabled) {
      return false;
    }
    char installId[INSTALL_ID_LENGTH + 1];
    const uint32_t high = esp_random();
    const uint32_t low = esp_random();
    snprintf(installId, sizeof(installId), "%08lX%08lX", static_cast<unsigned long>(high),
             static_cast<unsigned long>(low));
    // 新しいインストールでは、sequence を0から始める。
    if (preferences_.putULong(KEY_SEQUENCE, 0) != sizeof(uint32_t) || !putString(KEY_INSTALL_ID, installId)) {
      return false;
    }
    settings_.nextSequence = 0;
    strlcpy(settings_.installId, installId, sizeof(settings_.installId));
    return true;
  }

  // 1回の送信要求に1つのsequenceを割り当てる。次の値をNVSへ保存できたときだけ true を返す。
  // 保存に失敗したら送信しないこと(再起動で同じsequenceを使わないため)。
  bool reserveSequence(uint32_t &sequence) {
    if (!readyToSend()) {
      return false;
    }
    const uint32_t current = settings_.nextSequence;
    const uint32_t next = current + 1;
    if (preferences_.putULong(KEY_SEQUENCE, next) != sizeof(uint32_t)) {
      return false;
    }
    if (preferences_.getULong(KEY_SEQUENCE, current) != next) {
      return false;
    }
    settings_.nextSequence = next;
    sequence = current;
    return true;
  }

 private:
  bool putString(const char *key, const char *value) {
    return ready_ && preferences_.putString(key, value) == strlen(value);
  }

  void loadString(const char *key, char *out, size_t outSize, bool (*validator)(const char *)) {
    out[0] = '\0';
    if (!preferences_.isKey(key)) {
      return;
    }
    char buffer[MAX_WIFI_PASS_LENGTH + 1] = {};
    preferences_.getString(key, buffer, sizeof(buffer));
    // NVSの値も検証する。壊れた値は未設定として扱う(安全側)。
    if (validator(buffer) && strlen(buffer) < outSize) {
      strlcpy(out, buffer, outSize);
    }
    memset(buffer, 0, sizeof(buffer));
  }

  void load() {
    loadString(KEY_DEVICE_ID, settings_.deviceId, sizeof(settings_.deviceId), isValidDeviceId);
    loadString(KEY_KEY_ID, settings_.keyId, sizeof(settings_.keyId), isValidKeyId);
    loadString(KEY_INSTALL_ID, settings_.installId, sizeof(settings_.installId), isValidInstallId);
    loadString(KEY_SHELTER_CODE, settings_.shelterCode, sizeof(settings_.shelterCode), isValidShelterCode);
    loadString(KEY_WIFI_PASS, settings_.wifiPass, sizeof(settings_.wifiPass), isValidWifiPass);
    settings_.hmacKeyLength = 0;
    hmacKeyState_ = HmacKeyState::NotSet;
    if (preferences_.isKey(KEY_HMAC_KEY)) {
      // 32バイトでない鍵(旧ファームで保存した16バイトの鍵など)は読み込まず、送信しない。
      const size_t length = preferences_.getBytesLength(KEY_HMAC_KEY);
      if (length == HMAC_KEY_BYTES &&
          preferences_.getBytes(KEY_HMAC_KEY, settings_.hmacKey, HMAC_KEY_BYTES) == HMAC_KEY_BYTES) {
        settings_.hmacKeyLength = HMAC_KEY_BYTES;
        hmacKeyState_ = HmacKeyState::Set;
      } else {
        memset(settings_.hmacKey, 0, sizeof(settings_.hmacKey));
        hmacKeyState_ = HmacKeyState::InvalidLength;
      }
    }
    // sequence が読めないのに install_id がある状態は、番号の巻き戻りになり得るので送らない。
    if (hasInstallId() && !preferences_.isKey(KEY_SEQUENCE)) {
      settings_.nextSequence = SEQUENCE_EXHAUSTED;
    } else {
      settings_.nextSequence = preferences_.getULong(KEY_SEQUENCE, 0);
    }
  }

  Preferences preferences_;
  Settings settings_;
  HmacKeyState hmacKeyState_ = HmacKeyState::NotSet;
  bool ready_ = false;
};

}  // namespace device_settings
