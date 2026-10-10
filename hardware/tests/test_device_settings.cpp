// device_settings::Store::resetInstall()(NEWINSTALL)の各分岐を、PC上で確かめる小さなテスト。
// Arduino・NVS はスタブ(stubs/)。実機の動作の確認ではない。実行方法は docs/tbeam-provisioning.md。
#include <cstdio>

#include "Preferences.h"
#include "device_settings.h"

using device_settings::ResetInstallResult;

static int g_failed = 0;
#define CHECK(condition)                                                \
  do {                                                                  \
    if (!(condition)) {                                                 \
      ++g_failed;                                                       \
      std::printf("FAIL line %d: %s\n", __LINE__, #condition);          \
    }                                                                   \
  } while (0)

static const char OLD_ID[] = "A1B2C3D4E5F60718";

// install_id と sequence=42 が保存された端末(再起動後の状態)。
static device_settings::Store provisioned() {
  FakeNvs::get() = FakeNvs();
  device_settings::Store setup;
  setup.begin();
  setup.setDeviceId("TB001");
  setup.setKeyId("01");
  setup.setShelterCode("AIT001");
  setup.setHmacKeyHex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
  Preferences prefs;
  prefs.putString("install_id", OLD_ID);
  prefs.putULong("sequence", 42);
  device_settings::Store store;
  store.begin();
  return store;
}

static uint32_t nvsSequence() { return Preferences().getULong("sequence", 0xFFFFFFFFu); }

int main() {
  {  // Ok: install_id が消え、sequence が 0 に戻る。新しい install_id は古いものと違う
    auto store = provisioned();
    CHECK(store.readyToSend());
    CHECK(store.resetInstall() == ResetInstallResult::Ok);
    CHECK(!store.hasInstallId() && !FakeNvs::get().data.count("install_id") && nvsSequence() == 0);
    CHECK(store.ensureInstallId(true) && std::strcmp(store.settings().installId, OLD_ID) != 0);
  }
  {  // Ok: remove() が false でも、キーが無くなっていれば成功(キーが元から無い場合など)
    auto store = provisioned();
    FakeNvs::get().removeFalseButErases = true;
    CHECK(store.resetInstall() == ResetInstallResult::Ok && nvsSequence() == 0);
  }
  {  // NotReady: NVS を開いていない
    device_settings::Store store;
    CHECK(store.resetInstall() == ResetInstallResult::NotReady);
  }
  {  // RemoveFailed: キーが残ったら、何も変えない。再起動しても同じ install_id で番号が続く
    auto store = provisioned();
    FakeNvs::get().failRemove = true;
    CHECK(store.resetInstall() == ResetInstallResult::RemoveFailed);
    CHECK(store.hasInstallId() && std::strcmp(store.settings().installId, OLD_ID) == 0 && nvsSequence() == 42);
    uint32_t sequence = 0;
    CHECK(store.reserveSequence(sequence) && sequence == 42);
    device_settings::Store rebooted;
    rebooted.begin();
    CHECK(std::strcmp(rebooted.settings().installId, OLD_ID) == 0 && rebooted.settings().nextSequence == 43);
  }
  {  // RemoveFailed: remove() が true でも、キーが残っていれば失敗として扱う
    auto store = provisioned();
    FakeNvs::get().removeTrueButKeyRemains = true;
    CHECK(store.resetInstall() == ResetInstallResult::RemoveFailed && nvsSequence() == 42);
  }
  {  // SequenceResetFailed: 古い install_id は使わず、新しい install_id ができるまで送信しない
    auto store = provisioned();
    FakeNvs::get().failPutULongKey = "sequence";
    CHECK(store.resetInstall() == ResetInstallResult::SequenceResetFailed);
    uint32_t sequence = 0;
    CHECK(!store.hasInstallId() && !store.readyToSend() && !store.reserveSequence(sequence));
    FakeNvs::get().failPutULongKey = "";
    device_settings::Store rebooted;
    rebooted.begin();
    CHECK(!rebooted.hasInstallId() && !rebooted.readyToSend());
    CHECK(rebooted.ensureInstallId(true) && std::strcmp(rebooted.settings().installId, OLD_ID) != 0);
  }
  std::printf(g_failed == 0 ? "OK\n" : "NG: %d failed\n", g_failed);
  return g_failed == 0 ? 0 : 1;
}
