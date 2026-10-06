# LoRa Gateway Prep

T-Beam が届く前後で使う、Emergency Packet 受信確認用のメモです。

## 構成

```text
スマートフォン
  ↓ Wi-Fi: TSUNAGU-<device_id>
T-Beam A: 現場送信機（192.168.4.1）
  ↓ LoRa
T-Beam B: 本部受信機
  ↓ USBシリアル（115200 baud）
PC: tools/lora_serial_gateway.py
  ↓ HTTPS
Backend: POST /api/emergency-packets
```

送信機は Emergency Packet v2 を送ります(仕様は `docs/emergency-packet-v2.md`、送信機の初期設定は `docs/tbeam-provisioning.md`)。

```text
v2|device_id|key_id|install_id|sequence|reported_at|shelter_code|people_count|water_stock|status|request_code|hmac
```

v1(署名なし)の形式は次のとおりです。受信機とAPIは、設定によって v1 も扱えます。

```text
v1|AIT001|21:04|170|18|WARNING|REQ_WATER
```

## 実装ファイル

- `hardware/TBeamEmergencySender/TBeamEmergencySender.ino`: Wi-Fi AP、フォーム配信、入力検証、USBシリアルの設定コマンド、LoRa送信
- `hardware/TBeamEmergencySender/device_config.h`: 無線設定とWi-Fi名の接頭辞(端末ごとの値・鍵・パスワードは書かない)
- `hardware/TBeamEmergencySender/device_settings.h`: 端末ごとの設定をNVSに保存する
- `hardware/TBeamEmergencySender/emergency_packet_v2.h`: v2 Packet の生成とHMAC
- `hardware/TBeamEmergencySender/carrier_sense.h`: 送信前キャリアセンス
- `hardware/TBeamEmergencySender/portal_html.h`: フロント提供フォームを組み込んだArduino用ヘッダー
- `tools/embed_tbeam_portal.py`: フロント提供フォームからArduino用ヘッダーを生成する同期ツール
- `hardware/TBeamEmergencyReceiver/TBeamEmergencyReceiver.ino`: LoRa受信、シリアルへのPacket出力

## フロント提供フォームとの接続

フォームのHTML/CSS/JSは`tools/tbeam-emergency-form.html`で管理し、次のコマンドで`portal_html.h`へ埋め込みます。

```powershell
python tools/embed_tbeam_portal.py
```

同期済みか確認する場合は、次を実行します。

```powershell
python tools/embed_tbeam_portal.py --check
```

Arduino側が受け付ける契約は次のとおりです。

- 表示用: `GET /info` → `{"device_id": "...", "shelter_code": "..."}`(秘密は返さない)
- 送信先: `POST /send`
- Content-Type: `application/x-www-form-urlencoded`
- `reported_at`: Unix秒(UTC、10進)。スマートフォンの時計の値で、2024-01-01より前は拒否する
- `people_count`: 0〜1,000,000の整数
- `water_stock`: 0〜1,000,000の整数
- `status`: `NORMAL` / `WARNING` / `ALERT` / `CRITICAL`
- `request_code`: `REQ_WATER` / `REQ_MEDICAL` / `REQ_FOOD` / `REQ_RESCUE` / `REQ_CONFIRM` / `NONE`
- 応答: JSON `{"ok": true/false, "message": "..."}`。送信中の二重要求は 409

避難所コードは、T-Beam の NVS に設定した値を使います。フォームでは選べず、`GET /info` の値を読み取り専用で表示します。端末ID・通し番号(sequence)・署名(hmac)は T-Beam が付け、ブラウザには渡しません。Arduino側でも全項目を再検証し、不正な入力はLoRaへ送りません。

避難所コードの割り振り規則は `[組織コード3文字][3桁連番]` （例: `AIT001`）とします。

`portal_html.h`は生成ファイルです。フォームを変更するときは`tools/tbeam-emergency-form.html`を編集し、同期コマンドを再実行してください。

## Arduino IDEで検証する

Arduino IDEへ次を導入します。

1. Boards ManagerからEspressifのESP32ボードパッケージを導入する。
2. Library Managerから`RadioLib`と`XPowersLib`を導入する。
3. ボードはT-Beamで従来使用した設定、未設定なら`ESP32 Dev Module`を選ぶ。
4. 送信側は`hardware/TBeamEmergencySender/TBeamEmergencySender.ino`を開く。
5. 受信側は`hardware/TBeamEmergencyReceiver/TBeamEmergencyReceiver.ino`を開く。
6. Arduino IDEの「検証」で両方をコンパイルする。

ボード定義とライブラリの版、書き込み後の初期設定(device_id、鍵、避難所コード、Wi-Fiのパスワード)は `docs/tbeam-provisioning.md` を参照してください。`hardware/TBeamEmergencySender/device_config.h` には、受信機と一致させる `TSUNAGU_RADIO_*` だけを置いています。

無線設定は送信側と受信側で完全に一致させます。リポジトリの初期値は日本向け920MHzモデルを想定した出発点であり、実際に以前疎通した設定、使用機器の技適表示、利用場所の条件を確認してから送信してください。

## スマートフォンからの操作

1. Wi-Fi設定から`TSUNAGU-<device_id>`へ接続する。
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

## ゲートウェイのAPIキー設定(lora_serial_gateway.py実行前に必要)

`tools/lora_serial_gateway.py`は`POST /api/emergency-packets`への送信時に`X-Gateway-Key`ヘッダーでAPIキー認証を行います(Cognitoログインではなく固定APIキー方式)。実行前に`TSUNAGU_GATEWAY_API_KEY`環境変数の設定が必要です。

### ローカル(Docker)の場合

`docker-compose.yml`に既定値`GATEWAY_API_KEY: local-gateway-key`が設定されています。同じ値をPC側にも設定します。

```powershell
$env:TSUNAGU_GATEWAY_API_KEY="local-gateway-key"
```

### 本番(AWS)の場合

本番のキーはTerraformが自動生成し、SSM Parameter Storeに保存されています。パラメータ名(パス)は`infra/terraform`ディレクトリで次を実行すると確認できます。

```powershell
terraform output -raw gateway_api_key_parameter
```

取得したパラメータ名を使って、値そのものを取得します。

```powershell
aws ssm get-parameter --name "<上で確認したパラメータ名>" --with-decryption --query "Parameter.Value" --output text
```

AWS CLIが使えない場合は、AWSコンソールの Systems Manager → Parameter Store から同じパラメータ名を検索し、「表示」で復号した値を確認することもできます。

取得した値をPowerShellの環境変数に設定します。

```powershell
$env:TSUNAGU_GATEWAY_API_KEY="<取得した値>"
```

**注意: `$env:`で設定した環境変数は、そのPowerShellウィンドウ(セッション)限りです。** 別のターミナルウィンドウを新しく開いて`lora_serial_gateway.py`を実行する場合は、その都度この設定をやり直す必要があります。値は画面共有やログに表示しないよう注意してください。

### トラブルシューティング: エラーが出たらまずここを疑う

`TSUNAGU_GATEWAY_API_KEY`が未設定のまま実行すると、通信を試みる前に次のエラーで**即終了(SystemExit)**します。

```text
TSUNAGU_GATEWAY_API_KEY is required
```

このエラーが出た場合は、今使っているPowerShellウィンドウでこの環境変数を設定できているか(別ウィンドウで設定して満足していないか)をまず確認してください。

スクリプト自体は起動したものの、送信時に`401`が返る場合は、環境変数に設定した値がSSM Parameter Storeに保存されている実際の値と一致していない可能性が高いです(コピペミス、古い値の使い回し、ローカル用の`local-gateway-key`のまま本番URLへ送っている、など)。SSMの値と手元の環境変数を突き合わせて確認してください。

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

- スマートフォンに`TSUNAGU-<device_id>`が表示される。
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
