"""Emergency Packet v2 の端末台帳(device_id → {key_id: 鍵})。

鍵はGit管理外で渡す。次のどちらか一方を使う(両方の指定はエラー)。
- PACKET_DEVICE_KEYS: JSON文字列
- PACKET_DEVICE_KEYS_FILE: 同じ形式のJSONファイルのパス(秘密情報ファイル)

形式: {"TB001": {"01": "<鍵の16進>"}, "TB002": {"01": "...", "02": "..."}}

端末の無効化は PACKET_DISABLED_DEVICES(device_idのカンマ区切り)で行う。
台帳から消すと「不明な端末」になるが、無効化なら監査ログで区別できる。

鍵の値はログ・例外メッセージ・reprに出さないこと。
"""

import json
import os
from dataclasses import dataclass, field
from enum import StrEnum
from re import fullmatch

MIN_KEY_BYTES = 16


class PacketKeyConfigError(RuntimeError):
    pass


class KeyLookupFailure(StrEnum):
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"
    DEVICE_DISABLED = "DEVICE_DISABLED"
    UNKNOWN_KEY_ID = "UNKNOWN_KEY_ID"


@dataclass(frozen=True)
class DeviceKeyRegistry:
    # repr=False: 例外やログに台帳ごと出力されても鍵が漏れないようにする。
    keys: dict[str, dict[str, bytes]] = field(repr=False)
    disabled_devices: frozenset[str]

    def lookup(self, device_id: str, key_id: str) -> bytes | KeyLookupFailure:
        device_keys = self.keys.get(device_id)
        if device_keys is None:
            return KeyLookupFailure.UNKNOWN_DEVICE
        if device_id in self.disabled_devices:
            return KeyLookupFailure.DEVICE_DISABLED
        key = device_keys.get(key_id)
        if key is None:
            return KeyLookupFailure.UNKNOWN_KEY_ID
        return key


def _read_ledger_source() -> str:
    inline = os.getenv("PACKET_DEVICE_KEYS", "").strip()
    path = os.getenv("PACKET_DEVICE_KEYS_FILE", "").strip()
    if inline and path:
        raise PacketKeyConfigError("Set only one of PACKET_DEVICE_KEYS or PACKET_DEVICE_KEYS_FILE")
    if path:
        try:
            with open(path, encoding="utf-8") as ledger_file:
                return ledger_file.read()
        except OSError:
            raise PacketKeyConfigError("PACKET_DEVICE_KEYS_FILE could not be read") from None
    return inline or "{}"


def _parse_ledger(source: str) -> dict[str, dict[str, bytes]]:
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        # 元の例外は本文の一部を含み得るので連鎖させない。
        raise PacketKeyConfigError("Packet device key ledger is not valid JSON") from None
    if not isinstance(data, dict):
        raise PacketKeyConfigError("Packet device key ledger must be a JSON object")

    ledger: dict[str, dict[str, bytes]] = {}
    for device_id, device_keys in data.items():
        if not isinstance(device_id, str) or not fullmatch(r"[A-Z0-9]{5}", device_id):
            raise PacketKeyConfigError("Packet device key ledger has an invalid device_id")
        if not isinstance(device_keys, dict) or not device_keys:
            raise PacketKeyConfigError(f"Packet device key ledger entry for {device_id} must be a non-empty object")
        ledger[device_id] = {}
        for key_id, key_hex in device_keys.items():
            if not isinstance(key_id, str) or not fullmatch(r"[0-9A-F]{2}", key_id):
                raise PacketKeyConfigError(f"Packet device key ledger has an invalid key_id for {device_id}")
            if not isinstance(key_hex, str) or not fullmatch(r"(?:[0-9a-fA-F]{2})+", key_hex):
                raise PacketKeyConfigError(f"Key {device_id}/{key_id} must be a hex string")
            key = bytes.fromhex(key_hex)
            if len(key) < MIN_KEY_BYTES:
                raise PacketKeyConfigError(f"Key {device_id}/{key_id} must be at least {MIN_KEY_BYTES} bytes")
            ledger[device_id][key_id] = key
    return ledger


def load_device_key_registry() -> DeviceKeyRegistry:
    disabled = frozenset(
        device_id.strip()
        for device_id in os.getenv("PACKET_DISABLED_DEVICES", "").split(",")
        if device_id.strip()
    )
    return DeviceKeyRegistry(keys=_parse_ledger(_read_ledger_source()), disabled_devices=disabled)
