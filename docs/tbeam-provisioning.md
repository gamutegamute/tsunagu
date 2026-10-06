# T-Beam 送信機の初期設定と実機確認

T-Beam 送信機(`hardware/TBeamEmergencySender`)を Emergency Packet v2 で使うための、書き込み・初期設定の手順と、実機担当向けのチェックリストです。
Packet の仕様は `docs/emergency-packet-v2.md`(バックエンドのPR)を正とします。

> この文書の手順・チェックリストは、実機ではまだ確認していません。ビルドが通ることだけを確認しています。

## ビルド環境(版をそろえる)

書き込むPCと実機担当で、次の版をそろえてください。

| 項目 | 版 |
|---|---|
| ボード定義 | `esp32:esp32` 3.3.12(Espressif、Boards Manager) |
| ボード(FQBN) | `esp32:esp32:esp32`(ESP32 Dev Module、オプションは既定値) |
| RadioLib | 7.8.1 |
| XPowersLib | 0.3.3 |
| arduino-cli | 1.4.1(Arduino IDE 2 に同梱のもの) |

版は、リポジトリに指定が無かったため、2026-10-06 時点の最新の安定版にしました。ボードは `docs/lora-gateway-prep.md` の「未設定なら ESP32 Dev Module」に合わせています。

arduino-cli でのビルド例(成果物はリポジトリの外に出す):

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 --build-path <リポジトリ外のフォルダ> hardware/TBeamEmergencySender
arduino-cli compile --fqbn esp32:esp32:esp32 --build-path <リポジトリ外のフォルダ> hardware/TBeamEmergencyReceiver
```

## 書き込み時の注意: Erase All Flash

端末の設定(device_id、鍵、install_id、sequence など)は、ESP32 の NVS に保存されます。

- Arduino IDE の「Erase All Flash Before Sketch Upload」を **Enabled** にして書き込むと、**NVS も消えます**。鍵の再設定が必要になり、install_id も新しくなります
- ファームの更新だけなら **Disabled**(既定値)のまま書き込んでください
- 端末を別の用途に回す・廃棄するときは、Erase All Flash で NVS を消してください

## 初期設定(USBシリアル)

1. T-Beam を USB で PC に接続し、シリアルモニタを **115200 baud**、改行コードを「LF」または「CRLF」にして開く
2. 次のコマンドを1行ずつ送る(`<...>` は実際の値に置き換える)

```text
SET device_id <英大文字・数字5文字>
SET key_id <英大文字の16進2文字>
SET key <鍵の16進。16〜64バイト>
SET shelter_code <3〜12文字(英大文字・数字・_・-)>
SET wifi_pass <8〜63文字の英数記号>
SHOW
```

3. RST ボタンを押して再起動する。Wi-Fi の AP `TSUNAGU-<device_id>` が起動し、install_id が作られる
4. もう一度 `SHOW` を送り、`ready_to_send: yes` になっていることを確認する

コマンド:

| コマンド | 内容 |
|---|---|
| `SET <項目> <値>` | 項目は `device_id` / `key_id` / `key` / `shelter_code` / `wifi_pass`。書式が不正なら保存しない |
| `SHOW` | 設定を表示する。`key` と `wifi_pass` は「set / (not set)」だけを表示し、値は出さない |
| `NEWINSTALL` | install_id を再発行し、sequence を 0 に戻す(Wi-Fi が止まっているときは、次に Wi-Fi が起動したときに作る) |
| `HELP` | 設定手順を表示する |

- 鍵とパスワードは、ファームがエコーもログ出力もしません。ただし、シリアルモニタの入力欄の履歴や、端末ソフトのログ機能には残ることがあります。設定後は、シリアルモニタを閉じる・ログを消すなどしてください
- ソース(`device_config.h` を含む)に、鍵やパスワードのデフォルト値はありません。未設定の項目がある間は送信しません
- `device_id` か `wifi_pass` が未設定の間は、Wi-Fi の AP を起動せず、シリアルに設定手順を表示します
- `install_id` と `sequence` は `SET` では変更できません(`NEWINSTALL` だけ)
- install_id は 64 ビットの乱数です。乱数源は `esp_random()` で、Wi-Fi(RF)を起動した後にだけ生成します(RF が動いている間はハードウェア乱数になるため)
- sequence は、送信要求ごとに1つ進み、送信前に NVS へ保存します。保存に失敗したら送信しません。`FFFFFFFF` に達したら送信しないので、`NEWINSTALL` してください

## 鍵の扱い

- 実物の鍵を、リポジトリ・チャット・チケット・スクリーンショット・ログに載せないでください。この文書にも書きません
- 鍵は端末ごとに別にし、サーバーの端末台帳(`PACKET_DEVICE_KEYS` または `PACKET_DEVICE_KEYS_FILE`)と同じ値を、同じ `device_id` / `key_id` で登録します
- 持ち運ぶときは、暗号化したファイルやパスワードマネージャーなど、アクセスを限った手段で渡してください。紙に書く場合は、設定後に破棄してください
- 鍵が漏れたかもしれないときは、新しい `key_id` で鍵を作り直し、サーバー側で古い鍵を外すか、端末を `PACKET_DISABLED_DEVICES` で無効化してください

## 送信の流れ

1. スマートフォンから `TSUNAGU-<device_id>` に接続し、`http://192.168.4.1/` を開く
2. 画面には、避難所コードと端末IDが読み取り専用で表示される(`GET /info`。秘密は返さない)
3. 人数・水在庫・緊急度・要請コードを入力して送信する。報告時刻(`reported_at`)は、スマートフォンの時計の Unix 秒
4. T-Beam が sequence を進めて NVS に保存し、HMAC を計算して Packet を作る
5. キャリアセンスをしてから送信する

### キャリアセンス(`carrier_sense.h`)

| 項目 | 値 |
|---|---|
| 周波数 | 920.6 MHz(`device_config.h`) |
| 判定 | RSSI を 5 ms 以上連続で測定し、-85 dBm 以上を一度でも検出したら使用中 |
| CAD | 補助のみ。RSSI 測定の前に1回行い、プリアンブルを検出したら使用中として扱う |
| 再試行 | 使用中なら 100〜500 ms のランダム待ちで、最大5回(最初の判定とあわせて最大6回測定) |
| すべて使用中 | 電波を出さず、画面に失敗を表示する(入力は残る) |
| 送信後の休止 | 50 ms 以上、次の送信を開始しない |
| 送信時間の上限 | `getTimeOnAir()` が 4 秒以上なら送信しない |

- 同じ送信要求の中の再試行では、同じ Packet(同じ sequence・同じ hmac)を使います。ボタンを押し直すと、新しい sequence の新しい報告になります
- v2 Packet の最大長は 131 バイトです。SF9 / BW125 kHz / CR 4/7 / プリアンブル8 / CRC あり の計算上の送信時間は約 0.94 秒です(起動時にシリアルへ `time_on_air_ms` を出します)
- シリアルログの例: `[cs] attempt=1 rssi_max=-110.0dBm threshold=-85.0dBm samples=... window_us=... cad=free result=clear`、`[tx] result=sent ... measured_ms=...`

## HMAC セルフテスト

ビルドフラグ `TSUNAGU_SELFTEST` を付けたときだけ、起動時に `docs/emergency-packet-v2.md` のテストベクトル(ダミー鍵 `00 01 … 1f`)を計算し、シリアルに `[selftest] HMAC test vector: OK` または `NG` を出します。通常のビルドには入りません。

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 --build-property "compiler.cpp.extra_flags=-DTSUNAGU_SELFTEST" --build-path <リポジトリ外のフォルダ> hardware/TBeamEmergencySender
```

## 実機担当向けチェックリスト

すべて未確認です。確認したら、日付・担当・使った機材を記録してください。

- [ ] 空きのときの送信: 周囲に信号が無い状態で、`[cs] result=clear` のあと `[tx] result=sent` になり、受信機が Packet を出力する
- [ ] 強い信号での見送り: 別の送信機を近くで連続送信させ、`rssi_max` が -85 dBm 以上になって `result=busy` と判定される
- [ ] 使用中のバックオフ: 使用中が続くと 100〜500 ms の待ちで最大5回再試行し、すべて使用中なら電波を出さずに `[tx] result=channel_busy` になり、画面に失敗が表示され、入力が残る
- [ ] 50 ms 休止: 連続して送信したとき、前の送信の終了から次の送信の開始までが 50 ms 以上ある(ロジックアナライザやSDRで確認)
- [ ] 最大 Packet の送信時間: 131 バイトの Packet の送信時間が 4 秒未満である(起動ログの `time_on_air_ms` と、実測の `measured_ms`)
- [ ] HMAC セルフテスト: `TSUNAGU_SELFTEST` ビルドで `[selftest] HMAC test vector: OK` が出る
- [ ] 再起動で番号が戻らない: 何回か送信してから再起動し、`SHOW` の `next_sequence` が戻っていない。サーバーで 409 にならない
- [ ] NVS 消去後に install_id が変わる: Erase All Flash で書き込み、設定し直すと install_id が変わり、sequence が 0 から始まる
- [ ] 受信機が v1・v2 を通す: 受信機のシリアルに、v1 と v2 の Packet が改変されずに1行ずつ出る。区切り数や長さが違うもの、制御文字を含むものは出ない
- [ ] サーバーで受理される: 実機の Packet が API で 201 になり、`signature_status=SIGNATURE_VALID` になる

### RadioLib / SX1276 で実機確認が必要な点

| 項目 | 内容 |
|---|---|
| RSSI の読み方 | LoRa モードで `startReceive()` のあと `getRSSI(false, true)`(RegRssiValue、オフセット -157 dBm)を読んでいる。この値が、帯域内の実際の電力と合うか |
| 受信帯域 | 受信帯域は LoRa の BW 125 kHz のまま測っている。切り替えはしていない。規格が求める測定帯域と合うか |
| RSSI の立ち上がり | 受信状態にしてから 1 ms 待って測り始めている。SX1276 の RSSI 更新に十分か |
| サンプル数 | 5 ms の間に SPI で何回読めるか(`samples=`)。間隔が空きすぎていないか |
| CAD の後の状態 | `scanChannel()` の後に `startReceive()`、測定後に `standby()`、その後 `transmit()` という順で、モード遷移に問題が無いか |
| 判定から送信までの時間 | RSSI 測定の終了から送信開始までの時間 |

## 規格の未確認事項(ARIB STD-T108)

次の点は確認していません。いずれも、**ARIB STD-T108 の最新の本文で確認が必要**です。

- 5 ms のキャリアセンスを行う方式で、1時間あたりの送信時間の合計に制限があるか(あれば、ファームで送信時間を積算して制限する必要がある)
- RSSI の判定基準(-85 dBm、5 ms 以上の連続測定、測定帯域)が、規格の要求と合っているか
- 送信時間の上限(4 秒)と、送信後の休止時間(50 ms)が、使用するチャネル・送信出力の条件で正しいか
