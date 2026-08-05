# LoRa Gateway Prep

T-Beam が届く前後で使う、Emergency Packet 受信確認用のメモです。

## 構成

```text
スマートフォン
  ↓ Wi-Fi: TSUNAGU-Emergency
T-Beam A: 現場送信機（192.168.4.1）
  ↓ LoRa
T-Beam B: 本部受信機
  ↓ USBシリアル（115200 baud）
PC: tools/lora_serial_gateway.py
  ↓ HTTPS
Backend: POST /api/emergency-packets
```

Emergency Packet は次の形式にします。

```text
v1|AIT001|21:04|170|18|WARNING|REQ_WATER
```

## 実装ファイル

- `hardware/TBeamEmergencySender/TBeamEmergencySender.ino`: Wi-Fi AP、フォーム配信、入力検証、LoRa送信
- `hardware/TBeamEmergencySender/device_config.h`: 避難所コード、AP、無線設定
- `hardware/TBeamEmergencySender/portal_html.h`: フロント提供フォームを組み込むための仮置き
- `hardware/TBeamEmergencyReceiver/TBeamEmergencyReceiver.ino`: LoRa受信、シリアルへのPacket出力

## フロント提供フォームとの接続

フォームのHTML/CSS/JSはフロント担当から受け取り、`portal_html.h`の`PORTAL_HTML`へ埋め込みます。Arduino側が受け付ける契約は次のとおりです。

- 送信先: `POST /send`
- Content-Type: `application/x-www-form-urlencoded`
- `time`: `HH:MM`
- `people_count`: 0以上の整数
- `water_stock`: 0以上の整数
- `status`: `NORMAL` / `WARNING` / `ALERT` / `CRITICAL`
- `request_code`: `REQ_WATER` / `REQ_MEDICAL` / `REQ_FOOD` / `REQ_RESCUE` / `REQ_CONFIRM` / `NONE`

避難所コードはフォームから受け取らず、`device_config.h`の固定値を使います。時刻はフロント側JavaScriptが送信直前に設定します。Arduino側でも全項目を再検証し、不正な入力はLoRaへ送りません。

フォーム内で避難所コードを確認表示する場所には`{{SHELTER_CODE}}`を入れます。T-Beamが配信前に設定値へ置き換えます。

現在の`portal_html.h`は接続確認用の仮表示だけです。フロント提供版を受け取るまでは報告フォームとして使用できません。

## Arduino IDEで検証する

Arduino IDEへ次を導入します。

1. Boards ManagerからEspressifのESP32ボードパッケージを導入する。
2. Library Managerから`RadioLib`と`XPowersLib`を導入する。
3. ボードはT-Beamで従来使用した設定、未設定なら`ESP32 Dev Module`を選ぶ。
4. 送信側は`hardware/TBeamEmergencySender/TBeamEmergencySender.ino`を開く。
5. 受信側は`hardware/TBeamEmergencyReceiver/TBeamEmergencyReceiver.ino`を開く。
6. Arduino IDEの「検証」で両方をコンパイルする。

送信機へ書き込む前に、`hardware/TBeamEmergencySender/device_config.h`を確認します。

- `TSUNAGU_SHELTER_CODE`: 送信機を置く避難所のコード
- `TSUNAGU_AP_PASSWORD`: 8文字以上の会場用パスワード
- `TSUNAGU_RADIO_*`: 受信機と一致するLoRa設定

無線設定は送信側と受信側で完全に一致させます。リポジトリの初期値は日本向け920MHzモデルを想定した出発点であり、実際に以前疎通した設定、使用機器の技適表示、利用場所の条件を確認してから送信してください。

## スマートフォンからの操作

1. Wi-Fi設定から`TSUNAGU-Emergency`へ接続する。
2. 自動で画面が出ない場合は、SafariまたはChromeで`http://192.168.4.1/`を開く。
3. 人数、水在庫、緊急度、要請を入力する。
4. `LoRaで報告する`を押す。

画面の`LoRa送出完了`は、送信側T-Beamが電波の送出処理を完了したことだけを示します。受信側からACKを返す仕組みはまだないため、`本部受信済み`とは表示しません。

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

1. 付属アンテナを接続してからT-Beamへ給電する。
2. 送信側、受信側の順にArduino IDEから書き込む。
3. スマートフォンから送信側のフォームを開けることを確認する。
4. Windowsのデバイスマネージャーで受信側のCOMポートを確認する。
5. 受信側のシリアルモニタを閉じる。
6. PCでシリアル中継を起動する。

```powershell
python .\tools\lora_serial_gateway.py --port COM3
```

`COM3` は実際に表示されたポート名に置き換えます。

## シリアルなしで中継だけ試す

```powershell
"v1|AIT001|21:04|170|18|WARNING|REQ_WATER" | python .\tools\lora_serial_gateway.py
```

## 確認ポイント

- スマートフォンに`TSUNAGU-Emergency`が表示される。
- `http://192.168.4.1/`で報告フォームが開く。
- 送信成功時の表示が`LoRa送出完了`であり、`本部受信済み`ではない。
- 受信側のシリアル出力は説明文なしのPacket 1行だけになる。
- `POST /api/emergency-packets` が 201 を返す。
- `GET /api/emergency-packets` に受信ログが出る。
- 不正な Packet は 400 になる。
- Packet には報告者名、メモ、Incident 詳細を入れない。
- 付属アンテナを接続してから送信する。

## 実機が必要な確認

次の項目はPCだけでは確認できません。

- Wi-Fi APが実際に電波を出すこと
- スマートフォンのキャプティブポータル表示
- SX1276の初期化とLoRa送受信
- RSSI、SNR、実用距離
- COMポート切断後の復旧
- 送信機からAWSのダッシュボードまでの一気通貫動作
