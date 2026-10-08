#include <DNSServer.h>
#include <RadioLib.h>
#include <SPI.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>

#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>

#include "carrier_sense.h"
#include "device_config.h"
#include "device_settings.h"
#include "emergency_packet_v2.h"
#include "portal_html.h"

namespace {

constexpr int I2C_SDA_PIN = 21;
constexpr int I2C_SCL_PIN = 22;
constexpr int RADIO_SCLK_PIN = 5;
constexpr int RADIO_MISO_PIN = 19;
constexpr int RADIO_MOSI_PIN = 27;
constexpr int RADIO_CS_PIN = 18;
constexpr int RADIO_DIO0_PIN = 26;
constexpr int RADIO_RESET_PIN = 23;
constexpr int RADIO_DIO1_PIN = 33;
constexpr int BOARD_LED_PIN = 4;
constexpr size_t SERIAL_LINE_MAX = 200;

const IPAddress ACCESS_POINT_IP(192, 168, 4, 1);
const IPAddress ACCESS_POINT_SUBNET(255, 255, 255, 0);

XPowersPMU powerManager;
SX1276 radio = new Module(RADIO_CS_PIN, RADIO_DIO0_PIN, RADIO_RESET_PIN, RADIO_DIO1_PIN);
DNSServer dnsServer;
WebServer webServer(80);
device_settings::Store settingsStore;
bool radioReady = false;
bool accessPointRunning = false;
bool transmitting = false;

char serialLine[SERIAL_LINE_MAX + 1];
size_t serialLineLength = 0;
bool serialLineOverflow = false;

// ---- Web ----

// message は固定の文言だけを渡す(入力値や秘密を入れない)。
void sendJson(int statusCode, bool ok, const char *message) {
  String body;
  body.reserve(64 + strlen(message));
  body += F("{\"ok\":");
  body += ok ? F("true") : F("false");
  body += F(",\"message\":\"");
  body += message;
  body += F("\"}");
  webServer.sendHeader("Cache-Control", "no-store");
  webServer.send(statusCode, "application/json; charset=utf-8", body);
}

void showPortal() {
  webServer.sendHeader("Cache-Control", "no-store");
  webServer.send_P(200, "text/html; charset=utf-8", PORTAL_HTML);
}

void redirectToPortal() {
  webServer.sendHeader("Location", "http://192.168.4.1/", true);
  webServer.send(302, "text/plain", "");
}

// 画面に読み取り専用で表示する値だけを返す。鍵・パスワード・install_id・sequenceは返さない。
void handleInfo() {
  const device_settings::Settings &settings = settingsStore.settings();
  String body;
  body.reserve(80);
  body += F("{\"device_id\":");
  if (settingsStore.hasDeviceId()) {
    body += '"';
    body += settings.deviceId;
    body += '"';
  } else {
    body += F("null");
  }
  body += F(",\"shelter_code\":");
  if (settingsStore.hasShelterCode()) {
    body += '"';
    body += settings.shelterCode;
    body += '"';
  } else {
    body += F("null");
  }
  body += '}';
  webServer.sendHeader("Cache-Control", "no-store");
  webServer.send(200, "application/json; charset=utf-8", body);
}

void handleSend() {
  // WebServerは1リクエストずつ処理するが、送信中の二重要求は明示的に断る。
  if (transmitting) {
    sendJson(409, false, "送信中です。現在の送信が終わるまでお待ちください。");
    return;
  }
  if (!radioReady) {
    sendJson(503, false, "LoRaを利用できません。T-Beamを再起動し、担当者へ連絡してください。");
    return;
  }
  if (!settingsStore.readyToSend()) {
    sendJson(503, false, "T-Beamの初期設定が済んでいないため送信できません。担当者へ連絡してください。");
    return;
  }

  emergency_packet_v2::Report report;
  if (!emergency_packet_v2::parseReport(webServer.arg("reported_at"), webServer.arg("people_count"),
                                        webServer.arg("water_stock"), webServer.arg("status"),
                                        webServer.arg("request_code"), report)) {
    sendJson(400, false, "人数・水在庫・緊急度・要請コード・端末の時刻を確認してください。");
    return;
  }

  // 1回の送信要求に1つのsequence。送信前にNVSへ保存し、保存できなければ送らない。
  uint32_t sequence = 0;
  if (!settingsStore.reserveSequence(sequence)) {
    Serial.println(F("[tx] sequence could not be saved to NVS; not transmitted"));
    sendJson(500, false, "通し番号を保存できなかったため送信しませんでした。担当者へ連絡してください。");
    return;
  }

  char packet[emergency_packet_v2::PACKET_BUFFER_SIZE];
  const size_t packetLength = emergency_packet_v2::buildPacket(settingsStore.settings(), sequence, report, packet);
  if (packetLength == 0) {
    Serial.println(F("[tx] packet could not be built; not transmitted"));
    sendJson(500, false, "送信内容を作れなかったため送信しませんでした。担当者へ連絡してください。");
    return;
  }

  Serial.printf("[tx] sequence=%08lX length=%u\n", static_cast<unsigned long>(sequence),
                static_cast<unsigned>(packetLength));
  transmitting = true;
  digitalWrite(BOARD_LED_PIN, LOW);
  // キャリアセンスの再試行では、同じPacket(同じsequence・同じhmac)を送る。
  const carrier_sense::Result result =
      carrier_sense::transmit(radio, reinterpret_cast<const uint8_t *>(packet), packetLength, Serial);
  digitalWrite(BOARD_LED_PIN, HIGH);
  transmitting = false;

  switch (result.outcome) {
    case carrier_sense::Outcome::Sent:
      Serial.print(F("transmitted: "));
      Serial.println(packet);
      sendJson(200, true, "LoRa送出完了。本部での受信はまだ保証されません。");
      return;
    case carrier_sense::Outcome::ChannelBusy:
      sendJson(503, false,
               "周波数が使用中のため送信しませんでした。入力内容はそのままです。少し待ってからもう一度送信してください。");
      return;
    case carrier_sense::Outcome::TooLong:
      sendJson(500, false, "送信時間が長すぎるため送信しませんでした。担当者へ連絡してください。");
      return;
    case carrier_sense::Outcome::RadioError:
    default:
      sendJson(503, false, "LoRa送信に失敗しました。入力内容はそのままです。もう一度送信してください。");
      return;
  }
}

// ---- USBシリアルの設定コマンド ----

void printSetupGuide() {
  Serial.println(F("[setup] Configure this sender over USB serial (115200 baud), then press RST:"));
  Serial.println(F("[setup]   SET device_id <5 chars A-Z0-9>"));
  Serial.println(F("[setup]   SET key_id <2 hex chars A-F0-9>"));
  Serial.println(F("[setup]   SET key <hex, exactly 32 bytes = 64 hex chars>   (not echoed)"));
  Serial.println(F("[setup]   SET shelter_code <3-12 chars A-Z0-9_->"));
  Serial.println(F("[setup]   SET wifi_pass <8-63 printable ASCII>   (not echoed)"));
  Serial.println(F("[setup]   SHOW / NEWINSTALL / HELP"));
  Serial.println(F("[setup] See docs/tbeam-provisioning.md"));
}

void printSetting(const __FlashStringHelper *name, bool isSet, const char *value) {
  Serial.print(name);
  Serial.print(F(": "));
  Serial.println(isSet ? value : "(not set)");
}

void showSettings() {
  const device_settings::Settings &settings = settingsStore.settings();
  printSetting(F("device_id"), settingsStore.hasDeviceId(), settings.deviceId);
  printSetting(F("key_id"), settingsStore.hasKeyId(), settings.keyId);
  // 鍵は状態だけを出す(set / invalid length / not set)。長さの値や鍵の中身は出さない。
  Serial.print(F("key: "));
  Serial.println(device_settings::hmacKeyStateLabel(settingsStore.hmacKeyState()));
  if (settingsStore.hmacKeyState() == device_settings::HmacKeyState::InvalidLength) {
    Serial.println(F("[setup] the stored key is not 32 bytes; this sender will not transmit. Set it again with SET key"));
  }
  Serial.print(F("install_id: "));
  Serial.println(settingsStore.hasInstallId() ? settings.installId : "(not generated yet; generated after Wi-Fi starts)");
  Serial.print(F("next_sequence: "));
  if (settings.nextSequence == device_settings::SEQUENCE_EXHAUSTED) {
    Serial.println(F("(unavailable; run NEWINSTALL)"));
  } else {
    Serial.printf("%08lX\n", static_cast<unsigned long>(settings.nextSequence));
  }
  printSetting(F("shelter_code"), settingsStore.hasShelterCode(), settings.shelterCode);
  Serial.print(F("wifi_pass: "));
  Serial.println(settingsStore.hasWifiPass() ? F("set") : F("(not set)"));
  Serial.print(F("access_point: "));
  if (accessPointRunning) {
    Serial.print(F("running SSID="));
    Serial.println(WiFi.softAPSSID());
  } else {
    Serial.println(F("stopped"));
  }
  Serial.print(F("radio: "));
  Serial.println(radioReady ? F("ready") : F("error"));
  Serial.print(F("ready_to_send: "));
  Serial.println(settingsStore.readyToSend() && accessPointRunning && radioReady ? F("yes") : F("no"));
}

bool equalsIgnoreCase(const char *a, const char *b) {
  return strcasecmp(a, b) == 0;
}

void handleSetCommand(char *arguments) {
  // arguments: "<item> <value>"。value は item の後の空白1つより後ろ全体(パスワードの空白を保つ)。
  char *separator = strchr(arguments, ' ');
  if (separator == nullptr) {
    Serial.println(F("error: usage SET <item> <value>"));
    return;
  }
  *separator = '\0';
  const char *item = arguments;
  const char *value = separator + 1;

  if (equalsIgnoreCase(item, "device_id")) {
    Serial.println(settingsStore.setDeviceId(value) ? F("device_id: saved (press RST to apply)")
                                                    : F("error: device_id must be 5 chars A-Z0-9"));
  } else if (equalsIgnoreCase(item, "key_id")) {
    Serial.println(settingsStore.setKeyId(value) ? F("key_id: saved")
                                                 : F("error: key_id must be 2 uppercase hex chars"));
  } else if (equalsIgnoreCase(item, "key")) {
    // 鍵はエコーしない。結果だけを返す。
    Serial.println(settingsStore.setHmacKeyHex(value) ? F("key: saved")
                                                      : F("error: key must be exactly 32 bytes = 64 hex chars (value not shown)"));
  } else if (equalsIgnoreCase(item, "shelter_code")) {
    Serial.println(settingsStore.setShelterCode(value) ? F("shelter_code: saved")
                                                       : F("error: shelter_code must be 3-12 chars A-Z0-9_-"));
  } else if (equalsIgnoreCase(item, "wifi_pass")) {
    Serial.println(settingsStore.setWifiPass(value)
                       ? F("wifi_pass: saved (press RST to apply)")
                       : F("error: wifi_pass must be 8-63 printable ASCII chars (value not shown)"));
  } else {
    Serial.println(F("error: unknown item (device_id, key_id, key, shelter_code, wifi_pass)"));
  }
}

void handleSerialCommand(char *line) {
  char *arguments = strchr(line, ' ');
  if (arguments != nullptr) {
    *arguments = '\0';
    ++arguments;
  }

  if (equalsIgnoreCase(line, "SET") && arguments != nullptr) {
    handleSetCommand(arguments);
  } else if (equalsIgnoreCase(line, "SHOW") && arguments == nullptr) {
    showSettings();
  } else if (equalsIgnoreCase(line, "NEWINSTALL") && arguments == nullptr) {
    if (!settingsStore.resetInstall()) {
      Serial.println(F("error: could not reset install_id/sequence in NVS"));
      return;
    }
    if (settingsStore.ensureInstallId(accessPointRunning)) {
      Serial.print(F("install_id: regenerated "));
      Serial.println(settingsStore.settings().installId);
    } else {
      Serial.println(F("install_id: cleared; a new one is generated after Wi-Fi starts"));
    }
    Serial.println(F("next_sequence: 00000000"));
  } else if (equalsIgnoreCase(line, "HELP")) {
    printSetupGuide();
  } else {
    Serial.println(F("error: unknown command (SET, SHOW, NEWINSTALL, HELP)"));
  }
}

void pollSerialConsole() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r' || c == '\n') {
      if (serialLineOverflow) {
        Serial.println(F("error: line too long"));
      } else if (serialLineLength > 0) {
        serialLine[serialLineLength] = '\0';
        handleSerialCommand(serialLine);
      }
      // 鍵やパスワードを含み得るので、処理後は入力行を消す。
      memset(serialLine, 0, sizeof(serialLine));
      serialLineLength = 0;
      serialLineOverflow = false;
      continue;
    }
    if (serialLineLength >= SERIAL_LINE_MAX) {
      serialLineOverflow = true;
      continue;
    }
    serialLine[serialLineLength++] = c;
  }
}

// ---- 初期化 ----

bool initializePower() {
  if (!powerManager.begin(Wire, AXP2101_SLAVE_ADDRESS, I2C_SDA_PIN, I2C_SCL_PIN)) {
    return false;
  }
  powerManager.setButtonBatteryChargeVoltage(3300);
  powerManager.enableButtonBatteryCharge();
  powerManager.setALDO2Voltage(3300);
  powerManager.enableALDO2();
  delay(100);
  return true;
}

bool initializeRadio() {
  SPI.begin(RADIO_SCLK_PIN, RADIO_MISO_PIN, RADIO_MOSI_PIN);
  const int state = radio.begin(
      TSUNAGU_RADIO_FREQUENCY_MHZ, TSUNAGU_RADIO_BANDWIDTH_KHZ,
      TSUNAGU_RADIO_SPREADING_FACTOR, TSUNAGU_RADIO_CODING_RATE,
      TSUNAGU_RADIO_SYNC_WORD, TSUNAGU_RADIO_OUTPUT_POWER_DBM,
      TSUNAGU_RADIO_PREAMBLE_LENGTH, 0);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.print(F("radio initialization failed: "));
    Serial.println(state);
    return false;
  }
  if (radio.setCRC(true) != RADIOLIB_ERR_NONE) {
    return false;
  }
  // 最大長のPacketの送信時間を起動時に確認する(4秒以上なら送信時にも拒否される)。
  Serial.printf("[radio] max packet length=%u time_on_air_ms=%lu\n",
                static_cast<unsigned>(emergency_packet_v2::MAX_PACKET_LENGTH),
                static_cast<unsigned long>(radio.getTimeOnAir(emergency_packet_v2::MAX_PACKET_LENGTH) / 1000));
  return true;
}

// device_id と wifi_pass が設定済みのときだけAPを起動する。
bool initializeAccessPoint() {
  if (!settingsStore.hasDeviceId() || !settingsStore.hasWifiPass()) {
    Serial.println(F("[setup] Wi-Fi AP is not started: device_id and wifi_pass are required."));
    return false;
  }
  char ssid[sizeof(TSUNAGU_AP_SSID_PREFIX) + device_settings::DEVICE_ID_LENGTH];
  snprintf(ssid, sizeof(ssid), "%s%s", TSUNAGU_AP_SSID_PREFIX, settingsStore.settings().deviceId);

  WiFi.mode(WIFI_AP);
  if (!WiFi.softAPConfig(ACCESS_POINT_IP, ACCESS_POINT_IP, ACCESS_POINT_SUBNET) ||
      !WiFi.softAP(ssid, settingsStore.settings().wifiPass)) {
    Serial.println(F("[setup] Wi-Fi AP failed to start"));
    return false;
  }
  Serial.print(F("[setup] Wi-Fi AP started: "));
  Serial.println(ssid);
  return true;
}

void startWebPortal() {
  dnsServer.start(53, "*", ACCESS_POINT_IP);
  webServer.on("/", HTTP_GET, showPortal);
  webServer.on("/info", HTTP_GET, handleInfo);
  webServer.on("/send", HTTP_POST, handleSend);
  webServer.on("/generate_204", HTTP_GET, showPortal);
  webServer.on("/hotspot-detect.html", HTTP_GET, showPortal);
  webServer.on("/connecttest.txt", HTTP_GET, showPortal);
  webServer.on("/ncsi.txt", HTTP_GET, showPortal);
  webServer.onNotFound(redirectToPortal);
  webServer.begin();
  Serial.print(F("portal ready: http://"));
  Serial.println(WiFi.softAPIP());
}

void indicateFatalError() {
  while (true) {
    digitalWrite(BOARD_LED_PIN, !digitalRead(BOARD_LED_PIN));
    delay(200);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(BOARD_LED_PIN, OUTPUT);
  digitalWrite(BOARD_LED_PIN, HIGH);

#ifdef TSUNAGU_SELFTEST
  emergency_packet_v2::runHmacSelfTest(Serial);
#endif

  if (!initializePower()) {
    Serial.println(F("power initialization failed"));
    indicateFatalError();
  }
  if (!settingsStore.begin()) {
    Serial.println(F("NVS initialization failed; this sender will not transmit"));
  }
  radioReady = initializeRadio();

  accessPointRunning = initializeAccessPoint();
  if (accessPointRunning) {
    // Wi-Fi(RF)が動いてから esp_random() で install_id を作る。
    if (!settingsStore.ensureInstallId(true)) {
      Serial.println(F("[setup] install_id could not be generated/saved; this sender will not transmit"));
    }
    startWebPortal();
  }

  if (!settingsStore.readyToSend() || !accessPointRunning) {
    printSetupGuide();
  }
  showSettings();
}

void loop() {
  pollSerialConsole();
  if (accessPointRunning) {
    dnsServer.processNextRequest();
    webServer.handleClient();
  }
  delay(2);
}
