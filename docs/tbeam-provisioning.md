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
SET key <鍵の16進。32バイト固定(16進で64文字)>
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
| `SHOW` | 設定を表示する。`key` は「set / invalid length / not set」、`wifi_pass` は「set / (not set)」だけを表示し、値は出さない |
| `NEWINSTALL` | install_id を再発行し、sequence を 0 に戻す(Wi-Fi が止まっているときは、次に Wi-Fi が起動したときに作る)。install_id を NVS から消せなかったときは、sequence を戻さずにエラーを出す(下記) |
| `HELP` | 設定手順を表示する |

- 鍵とパスワードは、ファームがエコーもログ出力もしません。ただし、シリアルモニタの入力欄の履歴や、端末ソフトのログ機能には残ることがあります。設定後は、シリアルモニタを閉じる・ログを消すなどしてください
- ソース(`device_config.h` を含む)に、鍵やパスワードのデフォルト値はありません。未設定の項目がある間は送信しません
- 鍵は**32バイト固定(16進で64文字)**です。サーバー(バックエンド)も32バイト以外の鍵をエラーにします。32バイト以外の鍵は `SET key` で保存しません
- NVS に保存済みの鍵が32バイトでない場合(例: 16〜64バイトを受け付けていた旧ファームで、32バイト以外の鍵を保存した端末)は、「鍵が無い」のと同じ扱いで送信しません。`SHOW` と起動時のログで `key: invalid length` と表示されるので、`SET key` で32バイトの鍵を入れ直してください
- `device_id` か `wifi_pass` が未設定の間は、Wi-Fi の AP を起動せず、シリアルに設定手順を表示します
- `install_id` と `sequence` は `SET` では変更できません(`NEWINSTALL` だけ)
- install_id は 64 ビットの乱数です。乱数源は `esp_random()` で、Wi-Fi(RF)を起動した後にだけ生成します(RF が動いている間はハードウェア乱数になるため)
- sequence は、送信要求ごとに1つ進み、送信前に NVS へ保存します。保存に失敗したら送信しません。`FFFFFFFF` に達したら送信しないので、`NEWINSTALL` してください
- `NEWINSTALL` は、**install_id を NVS から消せたことを確かめてから**、sequence を 0 に戻します。消せていないのに sequence だけ 0 に戻すと、再起動後に古い install_id と 0 から始まる sequence の組が再び使われ、サーバーに重複と判断されるためです
  - install_id を消せなかったとき: install_id も sequence も変えず、`error: could not remove install_id from NVS; install_id and sequence are unchanged` と出します。これまでの install_id と sequence で送信を続けられます
  - install_id を消せたが sequence を戻せなかったとき: 古い install_id は二度と使いません。新しい install_id ができるまで送信せず、`error: install_id was removed but sequence could not be reset; ...` と出します。もう一度 `NEWINSTALL` してください
- `NEWINSTALL` の各分岐は、PC 上の小さなテストで確かめられます(Arduino と NVS はスタブで、実機の動作の確認ではありません): リポジトリのルートで `g++ -std=c++17 -I hardware/tests/stubs -I hardware/TBeamEmergencySender hardware/tests/test_device_settings.cpp -o test_device_settings && ./test_device_settings` を実行し、`OK` が出ること(`hardware/tests/` はスケッチのフォルダの外にあるので、ファームのビルドには含まれません)

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
| 判定 | RSSI を 5 ms 以上連続で測定し、-85 dBm 以上を一度でも検出したら使用中(しきい値は `carrier_sense.h` の `BUSY_THRESHOLD_DBM` の1か所。アンテナ入力での較正は未実施) |
| 測定の受信帯域 | RSSI を測る間だけ、受信帯域を通信用の 125 kHz から **250 kHz** に広げ、測り終えたら 125 kHz に戻す(`SENSE_BANDWIDTH_KHZ`)。広げられなかった、または戻せなかったときは、電波を出さずにエラーにする。**実機では未確認** |
| CAD | 補助のみ。RSSI 測定の前に1回行い、プリアンブルを検出したら使用中として扱う |
| 再試行 | 使用中なら 100〜500 ms のランダム待ちで、最大5回(最初の判定とあわせて最大6回測定) |
| すべて使用中 | 電波を出さず、画面に失敗を表示する(入力は残る) |
| 送信後の休止 | 50 ms 以上、次の送信を開始しない |
| 送信時間の上限 | `getTimeOnAir()` が 4 秒以上なら送信しない |

- 同じ送信要求の中の再試行では、同じ Packet(同じ sequence・同じ hmac)を使います。ボタンを押し直すと、新しい sequence の新しい報告になります
- v2 Packet の最大長は 131 バイトです。SF9 / BW125 kHz / CR 4/7 / プリアンブル8 / CRC あり の計算上の送信時間は約 0.94 秒です(起動時にシリアルへ `time_on_air_ms` を出します)
- シリアルログの例: `[cs] attempt=1 rssi_max=-110.0dBm threshold=-85.0dBm sense_bw=250kHz samples=... window_us=... cad=free result=clear`、`[tx] result=sent ... measured_ms=...`

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
- [ ] 測定帯域の切り替えと復帰: `[cs]` のログに `sense_bw=250kHz` が出る。キャリアセンスの後も、送信が受信機で欠損なく受信できる(帯域が 125 kHz に戻っている)。連続して何回送っても受信できる
- [ ] 隣のチャネルの信号: 920.6 MHz の 200 kHz チャネルの端(±100 kHz 付近)に信号を置いたとき、`rssi_max` に現れる(測定帯域がチャネル全体を覆っている)ことを、信号発生器などで確認する
- [ ] 時計が狂った状態での送信: スマートフォンの時計を 2024 年より前(または大きくずらした値)にして送信し、端末が拒否せず送信する。端末のシリアルに `[report] reported_at looks unset; sending anyway` が出る(2024 年より前のときだけ)。サーバーで受理され、`time_trust=UNTRUSTED` になる
- [ ] 50 ms 休止: 連続して送信したとき、前の送信の終了から次の送信の開始までが 50 ms 以上ある(ロジックアナライザやSDRで確認)
- [ ] 最大 Packet の送信時間: 131 バイトの Packet の送信時間が 4 秒未満である(起動ログの `time_on_air_ms` と、実測の `measured_ms`)
- [ ] HMAC セルフテスト: `TSUNAGU_SELFTEST` ビルドで `[selftest] HMAC test vector: OK` が出る
- [ ] 再起動で番号が戻らない: 何回か送信してから再起動し、`SHOW` の `next_sequence` が戻っていない。サーバーで 409 にならない
- [ ] NVS 消去後に install_id が変わる: Erase All Flash で書き込み、設定し直すと install_id が変わり、sequence が 0 から始まる
- [ ] 受信機が v1・v2 を通す: 受信機のシリアルに、v1 と v2 の Packet が改変されずに1行ずつ出る。区切り数や長さが違うもの、制御文字を含むものは出ない
- [ ] サーバーで受理される: 実機の Packet が API で 201 になり、`signature_status=SIGNATURE_VALID` になる
- [ ] 鍵の長さ: 31バイト・33バイト・16バイトの鍵が、`SET key` で保存されずに `error: key must be exactly 32 bytes` で拒否される(シリアルに鍵の値が出ない)
- [ ] 鍵の長さ: 32バイト(16進で64文字)の鍵が保存され、`SHOW` で `key: set` になる
- [ ] 旧ファームからの更新: 旧ファームで16バイトの鍵を保存した端末に、新ファームを書き込む(Erase All Flash は Disabled)と、`SHOW` と起動時のログが `key: invalid length` になり、`ready_to_send: no` で送信しない
- [ ] 旧ファームからの更新: その端末で、`SET key` で32バイトの鍵を入れ直すと(再起動は不要)、`key: set` になって送信でき、サーバーで受理される。再起動後も `key: set` のまま

### RadioLib / SX1276 で実機確認が必要な点

| 項目 | 内容 |
|---|---|
| RSSI の読み方 | LoRa モードで `startReceive()` のあと `getRSSI(false, true)`(RegRssiValue、オフセット -157 dBm)を読んでいる。この値が、帯域内の実際の電力と合うか |
| 受信帯域 | 測定の間だけ LoRa の BW を 250 kHz に切り替え、終わったら 125 kHz に戻している(RadioLib の `setBandwidth()`)。切り替えと復帰が実際に効いているか(切り替え後に Packet を受信・送信できる)。LoRa モードの RegRssiValue が、設定した帯域の電力を反映するか(データシートでの確認と、既知の信号での比較が必要) |
| RSSI の立ち上がり | 受信状態にしてから 1 ms 待って測り始めている。SX1276 の RSSI 更新に十分か |
| サンプル数 | 5 ms の間に SPI で何回読めるか(`samples=`)。間隔が空きすぎていないか |
| CAD の後の状態 | `scanChannel()` の後に `startReceive()`、測定後に `standby()`、その後 `transmit()` という順で、モード遷移に問題が無いか |
| 判定から送信までの時間 | RSSI 測定の終了から送信開始までの時間 |

## 規格(ARIB STD-T108)について

**この節の数値は、PR のレビューの指摘にもとづく値で、ARIB STD-T108 の原文では確認していません**(公開されている PDF からは、本文を確認できませんでした)。原文の確認が済むまでは、事実として扱わず、この端末について「規格に適合している」とは書きません。

レビューの指摘にある内容:

- 920.6〜922.2 MHz の「5 ms 以上のキャリアセンス」方式では、送信は4秒未満、送信後は 50 ms 以上休止する(この端末は、この前提で作っている)
- 1時間あたり 360 秒の制限(と、送信時間の10倍の休止)は、922.4〜923.4 MHz の記述で、この帯域(920.6 MHz)の方式には一律には適用されない
- キャリアセンスのレベルはアンテナ入力で -80 dBm、帯域は 200 kHz × n
- 現在のしきい値 -85 dBm は、レビューの指摘にある -80 dBm より厳しい(使用中と判定されやすい)値。ただし、RegRssiValue の読み値のしきい値であり、アンテナ入力の電力との対応(アンテナ・フィルタ・RFスイッチの損失を含む)は較正していない

この端末の現状:

- 測定帯域: 測定の間だけ 250 kHz に切り替える(通信は 125 kHz)。LoRa モードでは 200 kHz を選べないため、200 kHz 以上で最も狭い値にした。実機での確認は未実施
- 「基本動作の確認」と「規格適合の確認」は、別に記録する。規格適合は未確認

原文で確認が必要な点:

- 上の各数値と、その適用範囲
- 送信時間の上限(4 秒)と休止時間(50 ms)が、使用するチャネル・送信出力の条件で正しいか
- 測定帯域に 250 kHz を使えるか(200 kHz × n に対して、広く測ることの扱い)
