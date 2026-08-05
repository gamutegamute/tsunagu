#pragma once

// These values must be identical to TBeamEmergencySender/device_config.h.
constexpr float TSUNAGU_RADIO_FREQUENCY_MHZ = 920.6F;
constexpr float TSUNAGU_RADIO_BANDWIDTH_KHZ = 125.0F;
constexpr uint8_t TSUNAGU_RADIO_SPREADING_FACTOR = 9;
constexpr uint8_t TSUNAGU_RADIO_CODING_RATE = 7;
constexpr uint8_t TSUNAGU_RADIO_SYNC_WORD = 0x12;
constexpr int8_t TSUNAGU_RADIO_OUTPUT_POWER_DBM = 13;
constexpr uint16_t TSUNAGU_RADIO_PREAMBLE_LENGTH = 8;
