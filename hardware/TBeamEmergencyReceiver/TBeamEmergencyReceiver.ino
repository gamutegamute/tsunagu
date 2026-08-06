#include <RadioLib.h>
#include <SPI.h>
#include <Wire.h>

#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>

#include "device_config.h"

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

XPowersPMU powerManager;
SX1276 radio = new Module(RADIO_CS_PIN, RADIO_DIO0_PIN, RADIO_RESET_PIN, RADIO_DIO1_PIN);
volatile bool packetReceived = false;

void markPacketReceived() {
  packetReceived = true;
}

bool hasEmergencyPacketShape(const String &packet) {
  if (!packet.startsWith("v1|") || packet.length() > 160) {
    return false;
  }
  int delimiterCount = 0;
  for (size_t index = 0; index < packet.length(); ++index) {
    if (packet[index] == '|') {
      ++delimiterCount;
    }
  }
  return delimiterCount == 6;
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
    return false;
  }
  if (radio.setCRC(true) != RADIOLIB_ERR_NONE) {
    return false;
  }
  radio.setPacketReceivedAction(markPacketReceived);
  return radio.startReceive() == RADIOLIB_ERR_NONE;
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

  // Keep setup logs off Serial: the Python gateway treats every non-empty line as a packet.
  if (!initializePower() || !initializeRadio()) {
    indicateFatalError();
  }
}

void loop() {
  if (!packetReceived) {
    delay(2);
    return;
  }

  packetReceived = false;
  String packet;
  const int state = radio.readData(packet);
  if (state == RADIOLIB_ERR_NONE && hasEmergencyPacketShape(packet)) {
    Serial.println(packet);
    digitalWrite(BOARD_LED_PIN, !digitalRead(BOARD_LED_PIN));
  }
  radio.startReceive();
}
