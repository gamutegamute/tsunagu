#pragma once

// Set one shelter code per sender before writing the firmware.
constexpr char TSUNAGU_SHELTER_CODE[] = "AIT001";

constexpr char TSUNAGU_AP_SSID[] = "TSUNAGU-Emergency";
// This is a public demo default. Change it before using the device at a venue.
constexpr char TSUNAGU_AP_PASSWORD[] = "change-before-demo";

// These values must match the receiver and the settings already verified on the actual devices.
// Do not change radio parameters independently on only one side.
constexpr float TSUNAGU_RADIO_FREQUENCY_MHZ = 920.6F;
constexpr float TSUNAGU_RADIO_BANDWIDTH_KHZ = 125.0F;
constexpr uint8_t TSUNAGU_RADIO_SPREADING_FACTOR = 9;
constexpr uint8_t TSUNAGU_RADIO_CODING_RATE = 7;
constexpr uint8_t TSUNAGU_RADIO_SYNC_WORD = 0x12;
constexpr int8_t TSUNAGU_RADIO_OUTPUT_POWER_DBM = 13;
constexpr uint16_t TSUNAGU_RADIO_PREAMBLE_LENGTH = 8;
