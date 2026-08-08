#include <DNSServer.h>
#include <RadioLib.h>
#include <SPI.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>

#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>

#include "device_config.h"
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
constexpr int MAX_REPORT_VALUE = 1000000;

const IPAddress ACCESS_POINT_IP(192, 168, 4, 1);
const IPAddress ACCESS_POINT_SUBNET(255, 255, 255, 0);

XPowersPMU powerManager;
SX1276 radio = new Module(RADIO_CS_PIN, RADIO_DIO0_PIN, RADIO_RESET_PIN, RADIO_DIO1_PIN);
DNSServer dnsServer;
WebServer webServer(80);
bool radioReady = false;
bool transmitting = false;

const char *const ALLOWED_STATUSES[] = {"NORMAL", "WARNING", "ALERT", "CRITICAL"};
const char *const ALLOWED_REQUEST_CODES[] = {
    "REQ_WATER", "REQ_MEDICAL", "REQ_FOOD", "REQ_RESCUE", "REQ_CONFIRM", "NONE"};
const char *const ALLOWED_SHELTER_CODES[] = {"AIT001", "AIT002", "AIT003"};

bool isAllowedValue(const String &value, const char *const allowedValues[], size_t valueCount) {
  for (size_t index = 0; index < valueCount; ++index) {
    if (value == allowedValues[index]) {
      return true;
    }
  }
  return false;
}

bool isValidShelterCode(const char *code) {
  const size_t length = strlen(code);
  if (length < 3 || length > 32) {
    return false;
  }
  for (size_t index = 0; index < length; ++index) {
    const char character = code[index];
    const bool allowed = (character >= 'A' && character <= 'Z') ||
                         (character >= '0' && character <= '9') || character == '_' || character == '-';
    if (!allowed) {
      return false;
    }
  }
  return true;
}

bool isValidTime(const String &value) {
  if (value.length() != 5 || value[2] != ':') {
    return false;
  }
  const size_t digitIndexes[] = {0, 1, 3, 4};
  for (size_t index = 0; index < 4; ++index) {
    const char character = value[digitIndexes[index]];
    if (character < '0' || character > '9') {
      return false;
    }
  }
  const int hour = value.substring(0, 2).toInt();
  const int minute = value.substring(3, 5).toInt();
  return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
}

bool parseReportValue(const String &rawValue, int &parsedValue) {
  if (rawValue.length() == 0 || rawValue.length() > 7) {
    return false;
  }
  for (size_t index = 0; index < rawValue.length(); ++index) {
    if (rawValue[index] < '0' || rawValue[index] > '9') {
      return false;
    }
  }
  const unsigned long value = strtoul(rawValue.c_str(), nullptr, 10);
  if (value > MAX_REPORT_VALUE) {
    return false;
  }
  parsedValue = static_cast<int>(value);
  return true;
}

String escapeHtml(String value) {
  value.replace("&", "&amp;");
  value.replace("<", "&lt;");
  value.replace(">", "&gt;");
  value.replace("\"", "&quot;");
  return value;
}

void sendResultPage(int statusCode, const String &title, const String &message, bool success) {
  const char *accent = success ? "#0f7665" : "#b4232a";
  String body;
  body.reserve(1400 + message.length());
  body += F("<!doctype html><html lang=\"ja\"><meta charset=\"utf-8\">");
  body += F("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">");
  body += F("<title>");
  body += escapeHtml(title);
  body += F("</title><style>body{font-family:system-ui,sans-serif;background:#edf3ef;margin:0;padding:24px;color:#17211f}");
  body += F("main{max-width:440px;margin:auto;background:#fff;border:1px solid #ccd7d2;border-radius:8px;padding:24px}");
  body += F("h1{font-size:22px}.status{border-left:6px solid ");
  body += accent;
  body += F(";padding:12px;background:#f6f8f7;line-height:1.6}a{display:block;margin-top:24px;color:#0f7665;font-weight:700}</style>");
  body += F("<main><h1>");
  body += escapeHtml(title);
  body += F("</h1><p class=\"status\">");
  body += escapeHtml(message);
  body += F("</p><a href=\"/\">入力画面に戻る</a></main></html>");
  webServer.sendHeader("Cache-Control", "no-store");
  webServer.send(statusCode, "text/html; charset=utf-8", body);
}

void showPortal() {
  String body = FPSTR(PORTAL_HTML);
  body.replace("{{SHELTER_CODE}}", escapeHtml(TSUNAGU_SHELTER_CODE));
  webServer.sendHeader("Cache-Control", "no-store");
  webServer.send(200, "text/html; charset=utf-8", body);
}

void redirectToPortal() {
  webServer.sendHeader("Location", "http://192.168.4.1/", true);
  webServer.send(302, "text/plain", "");
}

void handleSend() {
  if (transmitting) {
    sendResultPage(409, "送信中です", "現在の送出が終わるまでお待ちください。", false);
    return;
  }
  if (!radioReady) {
    sendResultPage(503, "LoRaを利用できません", "T-Beamを再起動し、担当者へ連絡してください。", false);
    return;
  }

  const String shelterCode = webServer.arg("shelter_code");
  const String packetTime = webServer.arg("time");
  const String peopleCountText = webServer.arg("people_count");
  const String waterStockText = webServer.arg("water_stock");
  const String status = webServer.arg("status");
  const String requestCode = webServer.arg("request_code");
  int peopleCount = 0;
  int waterStock = 0;

  const bool isAllowedShelter = (shelterCode == TSUNAGU_SHELTER_CODE) || 
                                isAllowedValue(shelterCode, ALLOWED_SHELTER_CODES, sizeof(ALLOWED_SHELTER_CODES) / sizeof(ALLOWED_SHELTER_CODES[0]));

  if (!isAllowedShelter || !isValidTime(packetTime) ||
      !parseReportValue(peopleCountText, peopleCount) ||
      !parseReportValue(waterStockText, waterStock) ||
      !isAllowedValue(status, ALLOWED_STATUSES, sizeof(ALLOWED_STATUSES) / sizeof(ALLOWED_STATUSES[0])) ||
      !isAllowedValue(requestCode, ALLOWED_REQUEST_CODES,
                      sizeof(ALLOWED_REQUEST_CODES) / sizeof(ALLOWED_REQUEST_CODES[0]))) {
    sendResultPage(400, "入力エラー", "避難所コード・時刻・人数・水在庫・緊急度・要請コードを確認してください。", false);
    return;
  }

  String packet;
  packet.reserve(96);
  packet += F("v1|");
  packet += shelterCode;
  packet += '|';
  packet += packetTime;
  packet += '|';
  packet += peopleCount;
  packet += '|';
  packet += waterStock;
  packet += '|';
  packet += status;
  packet += '|';
  packet += requestCode;

  transmitting = true;
  digitalWrite(BOARD_LED_PIN, LOW);
  const int transmissionState = radio.transmit(packet);
  digitalWrite(BOARD_LED_PIN, HIGH);
  transmitting = false;

  if (transmissionState == RADIOLIB_ERR_NONE) {
    Serial.print(F("transmitted: "));
    Serial.println(packet);
    sendResultPage(200, "LoRa送出完了",
                   "T-Beamから電波を送出しました。本部での受信はまだ保証されません。", true);
    return;
  }

  Serial.print(F("transmit failed: "));
  Serial.println(transmissionState);
  sendResultPage(503, "LoRa送信に失敗しました", "入力内容を残したまま、もう一度送信してください。", false);
}

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
  return radio.setCRC(true) == RADIOLIB_ERR_NONE;
}

bool initializeAccessPoint() {
  if (!isValidShelterCode(TSUNAGU_SHELTER_CODE)) {
    Serial.println(F("shelter code must contain 3-32 uppercase letters, digits, '_' or '-'"));
    return false;
  }
  if (strlen(TSUNAGU_AP_PASSWORD) < 8 || strlen(TSUNAGU_AP_PASSWORD) > 63) {
    Serial.println(F("AP password must contain 8-63 characters"));
    return false;
  }
  WiFi.mode(WIFI_AP);
  if (!WiFi.softAPConfig(ACCESS_POINT_IP, ACCESS_POINT_IP, ACCESS_POINT_SUBNET)) {
    return false;
  }
  return WiFi.softAP(TSUNAGU_AP_SSID, TSUNAGU_AP_PASSWORD);
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

  if (!initializePower()) {
    Serial.println(F("power initialization failed"));
    indicateFatalError();
  }
  radioReady = initializeRadio();
  if (!initializeAccessPoint()) {
    Serial.println(F("access point initialization failed"));
    indicateFatalError();
  }

  dnsServer.start(53, "*", ACCESS_POINT_IP);
  webServer.on("/", HTTP_GET, showPortal);
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

void loop() {
  dnsServer.processNextRequest();
  webServer.handleClient();
  delay(2);
}
