# LoRa Gateway Prep

T-Beam が届く前後で使う、Emergency Packet 受信確認用のメモです。

## 構成

```text
T-Beam A: shelter sender
T-Beam B: headquarters receiver
PC: serial gateway
Backend: POST /api/emergency-packets
```

Emergency Packet は次の形式にします。

```text
v1|AIT001|21:04|170|18|WARNING|REQ_WATER
```

## 手動入力での確認

Docker で TSUNAGU を起動したあと、PowerShell で以下を実行します。

```powershell
.\tools\post_emergency_packet.ps1
```

PowerShell の実行ポリシーで止まる場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\post_emergency_packet.ps1
```

任意の Packet を送る場合:

```powershell
.\tools\post_emergency_packet.ps1 -Packet "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"
```

## T-Beam 到着後の流れ

1. T-Beam を microUSB ケーブルで PC に接続する。
2. Windows のデバイスマネージャーで COM ポートを確認する。
3. 受信側 T-Beam が受け取った Packet を `Serial.println(packet)` で1行出力する。
4. PC でシリアル中継を起動する。

```powershell
python .\tools\lora_serial_gateway.py --port COM3
```

`COM3` は実際に表示されたポート名に置き換えます。

## シリアルなしで中継だけ試す

```powershell
"v1|AIT001|21:04|170|18|WARNING|REQ_WATER" | python .\tools\lora_serial_gateway.py
```

## 確認ポイント

- `POST /api/emergency-packets` が 201 を返す。
- `GET /api/emergency-packets` に受信ログが出る。
- 不正な Packet は 400 になる。
- Packet には報告者名、メモ、Incident 詳細を入れない。
- 付属アンテナを接続してから送信する。
