#pragma once

// 送信前キャリアセンス(LBT)。
//
// 判定の本体はRSSIによるエネルギー検出で、CAD(LoRaのプリアンブル検出)は補助としてだけ使う。
// しきい値・測定時間・再試行回数などは、ARIB STD-T108の最新の本文で要件を確認してから変えること。
//
// RSSIを測る間だけ、受信帯域を通信用(125 kHz)から SENSE_BANDWIDTH_KHZ(250 kHz)に広げ、測り終えたら通信用へ戻す。
// 戻せなかったときは送信しない(RadioError)。
// SX1276での受信帯域の切り替え、RSSIの読み方は、実機での確認が済んでいない(docs/tbeam-provisioning.md)。

#include <Arduino.h>
#include <RadioLib.h>
#include <esp_random.h>

namespace carrier_sense {

// ---- 判定のしきい値(ここ1か所で決める) ----
// これ以上のRSSIを一度でも検出したら「使用中」と判定する。
//
// 注意: この値は、アンテナ入力でのRSSI較正が済んでいない。RegRssiValue の読み値(オフセット -157 dBm)と
// アンテナ入力の電力の対応は未確認で、アンテナ・フィルタ・RFスイッチの損失も含まれていない。
// PR のレビューの指摘では、キャリアセンスのレベルはアンテナ入力で -80 dBm とされている。この値は
// ARIB STD-T108 の原文では確認していない。-85 dBm は、その値より厳しい(使用中と判定されやすい)値だが、
// 較正が済むまでは数値の比較は目安でしかない。
// 原文の確認、帯域の切り替えの実機確認、較正が済むまで、この端末について「規格に適合」とは書かないこと。
constexpr float BUSY_THRESHOLD_DBM = -85.0F;
// RSSIを測る間だけ使う受信帯域(kHz)。PR のレビューの指摘では、キャリアセンスの帯域は 200 kHz × n とされている
// (ARIB STD-T108 の原文では確認していない)。
// SX1276のLoRaモードで選べる帯域のうち、200 kHz 以上で最も狭いのは 250 kHz(次は 500 kHz)。
constexpr float SENSE_BANDWIDTH_KHZ = 250.0F;
static_assert(SENSE_BANDWIDTH_KHZ >= 200.0F, "carrier sense bandwidth must cover a 200 kHz channel");
// RSSIを連続して測定する時間(5 ms以上)。
constexpr uint32_t SENSE_DURATION_US = 5000;
// 受信状態にしてからRSSIの読み取りを始めるまでの待ち時間。SX1276のRSSI更新の立ち上がり分(実機で要確認)。
constexpr uint32_t RECEIVE_SETTLE_US = 1000;
// 使用中のときの再試行(最初の判定とは別に最大5回)。
constexpr uint8_t MAX_RETRIES = 5;
constexpr uint32_t BACKOFF_MIN_MS = 100;
constexpr uint32_t BACKOFF_MAX_MS = 500;
// 送信後、次の送信を開始しない時間(50 ms以上)。
constexpr uint32_t POST_TRANSMIT_PAUSE_US = 50000;
// これ以上の送信時間になるPacketは送らない。
constexpr uint32_t MAX_TIME_ON_AIR_US = 4000000;
// LoRaのペイロード長の上限(255バイト未満)。
constexpr size_t MAX_PAYLOAD_LENGTH = 254;

enum class Outcome {
  Sent,
  ChannelBusy,
  TooLong,
  RadioError,
};

struct Result {
  Outcome outcome = Outcome::RadioError;
  uint8_t attempts = 0;
  uint32_t expectedTimeOnAirUs = 0;
  uint32_t measuredTransmitMs = 0;
  int16_t radioState = RADIOLIB_ERR_NONE;
};

struct SenseSample {
  bool busy = false;
  bool cadDetected = false;
  float maxRssiDbm = -200.0F;
  float senseBandwidthKhz = 0.0F;  // RSSIを測ったときの受信帯域(測っていなければ0)
  uint32_t sampleCount = 0;
  uint32_t windowUs = 0;
  int16_t radioState = RADIOLIB_ERR_NONE;
};

namespace detail {

inline uint32_t &lastTransmitEndUs() {
  static uint32_t value = 0;
  return value;
}

inline bool &hasTransmitted() {
  static bool value = false;
  return value;
}

inline void waitPostTransmitPause() {
  if (!hasTransmitted()) {
    return;
  }
  while (static_cast<uint32_t>(micros() - lastTransmitEndUs()) < POST_TRANSMIT_PAUSE_US) {
    delay(1);
  }
}

inline uint32_t randomBackoffMs() {
  // esp_random()はRF(Wi-Fi)が動いている間はハードウェア乱数になる。
  return BACKOFF_MIN_MS + (esp_random() % (BACKOFF_MAX_MS - BACKOFF_MIN_MS + 1));
}

}  // namespace detail

// CAD(補助)→ RSSIを5 ms以上連続測定、の順に行う。
// RSSIの測定を最後にして、判定から送信開始までの間を短くする。
// CADは通信用の帯域(125 kHz)のまま行い、RSSIの測定の間だけ受信帯域を広げて、終わったら通信用へ戻す。
// 戻せなかったとき(radioState が NONE 以外)は、呼び出し側が送信しないこと。
inline SenseSample senseChannel(SX1276 &radio, float communicationBandwidthKhz) {
  SenseSample sample;

  const int16_t cadState = radio.scanChannel();
  if (cadState == RADIOLIB_PREAMBLE_DETECTED) {
    sample.cadDetected = true;
  } else if (cadState != RADIOLIB_CHANNEL_FREE) {
    sample.radioState = cadState;
    return sample;
  }

  // 受信帯域を広げる。失敗したときは、狭い帯域のまま測らずに終える(念のため通信用へ戻しておく)。
  const int16_t widenState = radio.setBandwidth(SENSE_BANDWIDTH_KHZ);
  if (widenState != RADIOLIB_ERR_NONE) {
    radio.setBandwidth(communicationBandwidthKhz);
    sample.radioState = widenState;
    return sample;
  }
  sample.senseBandwidthKhz = SENSE_BANDWIDTH_KHZ;

  // LoRaモードの getRSSI(false, ...) はレジスタを読むだけなので、先に受信状態にする。
  const int16_t receiveState = radio.startReceive();
  if (receiveState == RADIOLIB_ERR_NONE) {
    delayMicroseconds(RECEIVE_SETTLE_US);

    const uint32_t startUs = micros();
    uint32_t elapsedUs = 0;
    do {
      const float rssi = radio.getRSSI(false, true);
      ++sample.sampleCount;
      if (rssi > sample.maxRssiDbm) {
        sample.maxRssiDbm = rssi;
      }
      if (rssi >= BUSY_THRESHOLD_DBM) {
        sample.busy = true;
      }
      elapsedUs = static_cast<uint32_t>(micros() - startUs);
    } while (elapsedUs < SENSE_DURATION_US);
    sample.windowUs = elapsedUs;
  }
  radio.standby();

  // 測定の成否にかかわらず、通信用の帯域へ戻す。戻せなければ、広い帯域のまま送信しないよう、エラーにする。
  const int16_t restoreState = radio.setBandwidth(communicationBandwidthKhz);
  if (receiveState != RADIOLIB_ERR_NONE) {
    sample.radioState = receiveState;
    return sample;
  }
  if (restoreState != RADIOLIB_ERR_NONE) {
    sample.radioState = restoreState;
    return sample;
  }

  // RSSIが空きでも、CADでLoRaのプリアンブルを検出していれば使用中として扱う(安全側)。
  if (sample.cadDetected) {
    sample.busy = true;
  }
  return sample;
}

inline void logSense(Print &log, uint8_t attempt, const SenseSample &sample) {
  log.printf(
      "[cs] attempt=%u rssi_max=%.1fdBm threshold=%.1fdBm sense_bw=%.0fkHz samples=%lu window_us=%lu cad=%s result=%s\n",
      attempt, sample.maxRssiDbm, BUSY_THRESHOLD_DBM, sample.senseBandwidthKhz,
      static_cast<unsigned long>(sample.sampleCount), static_cast<unsigned long>(sample.windowUs),
      sample.cadDetected ? "detected" : "free",
      sample.radioState != RADIOLIB_ERR_NONE ? "error" : (sample.busy ? "busy" : "clear"));
}

// 同じペイロードのまま、キャリアセンスと再試行を行って送信する。
// 呼び出し側は、再試行の間もペイロード(sequenceやhmacを含む)を作り直さないこと。
// communicationBandwidthKhz は通信用の帯域(radio.begin() に渡した値)。キャリアセンスの後に、この帯域へ戻す。
inline Result transmit(SX1276 &radio, const uint8_t *payload, size_t length, Print &log,
                       float communicationBandwidthKhz) {
  Result result;
  if (length == 0 || length > MAX_PAYLOAD_LENGTH) {
    result.outcome = Outcome::TooLong;
    log.printf("[tx] rejected: length=%u exceeds limit=%u\n", static_cast<unsigned>(length),
               static_cast<unsigned>(MAX_PAYLOAD_LENGTH));
    return result;
  }

  result.expectedTimeOnAirUs = static_cast<uint32_t>(radio.getTimeOnAir(length));
  if (result.expectedTimeOnAirUs >= MAX_TIME_ON_AIR_US) {
    result.outcome = Outcome::TooLong;
    log.printf("[tx] rejected: time_on_air_us=%lu limit_us=%lu\n",
               static_cast<unsigned long>(result.expectedTimeOnAirUs),
               static_cast<unsigned long>(MAX_TIME_ON_AIR_US));
    return result;
  }

  for (uint8_t attempt = 1; attempt <= MAX_RETRIES + 1; ++attempt) {
    result.attempts = attempt;
    detail::waitPostTransmitPause();

    const SenseSample sample = senseChannel(radio, communicationBandwidthKhz);
    logSense(log, attempt, sample);
    if (sample.radioState != RADIOLIB_ERR_NONE) {
      result.outcome = Outcome::RadioError;
      result.radioState = sample.radioState;
      log.printf("[tx] result=radio_error state=%d attempts=%u\n", sample.radioState, attempt);
      return result;
    }

    if (sample.busy) {
      if (attempt <= MAX_RETRIES) {
        const uint32_t backoffMs = detail::randomBackoffMs();
        log.printf("[cs] busy, retry %u/%u after %lu ms\n", attempt, MAX_RETRIES,
                   static_cast<unsigned long>(backoffMs));
        delay(backoffMs);
        continue;
      }
      result.outcome = Outcome::ChannelBusy;
      log.printf("[tx] result=channel_busy attempts=%u (not transmitted)\n", attempt);
      return result;
    }

    const uint32_t startMs = millis();
    result.radioState = radio.transmit(payload, length);
    result.measuredTransmitMs = millis() - startMs;
    detail::lastTransmitEndUs() = micros();
    detail::hasTransmitted() = true;

    result.outcome = result.radioState == RADIOLIB_ERR_NONE ? Outcome::Sent : Outcome::RadioError;
    log.printf("[tx] result=%s state=%d attempts=%u time_on_air_expected_ms=%lu measured_ms=%lu length=%u\n",
               result.outcome == Outcome::Sent ? "sent" : "radio_error", result.radioState, attempt,
               static_cast<unsigned long>(result.expectedTimeOnAirUs / 1000),
               static_cast<unsigned long>(result.measuredTransmitMs), static_cast<unsigned>(length));
    return result;
  }

  result.outcome = Outcome::ChannelBusy;
  return result;
}

}  // namespace carrier_sense
