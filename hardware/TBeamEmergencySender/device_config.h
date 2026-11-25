#pragma once

// 端末ごとの値(device_id、key_id、HMAC鍵、shelter_code、Wi-Fiのパスワード)は、ここには書かない。
// USBシリアルの SET コマンドでNVSへ書き込む(docs/tbeam-provisioning.md)。

// Wi-Fi名は TSUNAGU-<device_id>。
constexpr char TSUNAGU_AP_SSID_PREFIX[] = "TSUNAGU-";

// These values must match the receiver and the settings already verified on the actual devices.
// Do not change radio parameters independently on only one side.
constexpr float TSUNAGU_RADIO_FREQUENCY_MHZ = 920.6F;
constexpr float TSUNAGU_RADIO_BANDWIDTH_KHZ = 125.0F;
constexpr uint8_t TSUNAGU_RADIO_SPREADING_FACTOR = 9;
constexpr uint8_t TSUNAGU_RADIO_CODING_RATE = 7;
constexpr uint8_t TSUNAGU_RADIO_SYNC_WORD = 0x12;
constexpr int8_t TSUNAGU_RADIO_OUTPUT_POWER_DBM = 13;
constexpr uint16_t TSUNAGU_RADIO_PREAMBLE_LENGTH = 8;
