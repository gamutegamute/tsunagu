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

- 送信先: `POST /send`
- Content-Type: `application/x-www-form-urlencoded`
- `time`: `HH:MM`
- `people_count`: 0以上の整数
- `water_stock`: 0以上の整数
- `status`: `NORMAL` / `WARNING` / `ALERT` / `CRITICAL`
- `request_code`: `REQ_WATER` / `REQ_MEDICAL` / `REQ_FOOD` / `REQ_RESCUE` / `REQ_CONFIRM` / `NONE`

避難所コードは、フォーム上の選択肢から送信されます。送信機側の容量削減および不整合防止のため、フォーム上には日本語名を持たせず「AIT001」といったコードのみを表示します。初期値（デフォルト）には `device_config.h` の設定が使用され、URLパラメータで事前入力されている場合はそちらが優先的に選択されます。時刻はフロント側JavaScriptが送信直前に設定します。Arduino側でも全項目（許可リストに含まれる、あるいは自身のデフォルト避難所コードかどうかの検証を含む）を再検証し、不正な入力はLoRaへ送りません。

避難所コードの割り振り規則は `[組織コード3文字][3桁連番]` （例: `AIT001`）とします。

フォーム内で避難所コードの初期値（デフォルト）を埋め込む場所には`{{SHELTER_CODE}}`を入れます。T-Beamが配信前に設定値へ置き換えます。

`portal_html.h`は生成ファイルです。フォームを変更するときは`tools/tbeam-emergency-form.html`を編集し、同期コマンドを再実行してください。

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

`401` が返ると、ゲートウェイは**送信を停止**します(下の「ゲートウェイの送信とエラーの扱い」)。ログに `sending is STOPPED (configuration error: HTTP_401 ...)` と出ます。受信とキューへの保存は続くので、値を直したら、ゲートウェイを再起動してください。キューに残った Packet から送信が再開されます。

## ゲートウェイの送信とエラーの扱い

`tools/lora_serial_gateway.py` は、受信した Packet を**ローカルのAPI 1つ**(`--api-url`、デフォルト `http://localhost:8000/api/emergency-packets`)へ送ります。HMAC(署名)の検証はサーバーの役割なので、ゲートウェイではしません。

### 受信とキュー

- 受信した行のうち、Emergency Packet の形のものだけをキューへ入れます。v1 は区切り6個(160文字以下)、v2 は区切り11個(131文字以下)で、印字できるASCII文字だけのもの
- 形が正しくない行は捨てます。ログには、長さと理由(`unknown_version` / `delimiter_count` / `too_long` / `non_printable`)だけを出し、内容は出しません
- Packet(raw packet)は改変しません。行末の改行だけを取り除きます
- キューは SQLite(`.tsunagu/lora_gateway_queue.db`、`--queue-db` で変更可)です。キューの列: `id`、`packet`、`queued_at`、`status`、`hub_received_at`、`attempts`、`next_attempt_at`
- 古い形式のキューのファイルは、起動時に、足りない列だけを追加します(データは消しません)。古い行は `queued_at` を `hub_received_at` の代わりに使います
- `hub_received_at` は、ゲートウェイがシリアルで受信した時刻(UTC)です。`2026-10-06T12:00:00.123Z` の形で保存し、そのままAPIへ送ります
- `status` は、Packet を `|` で分けた位置から取り出します(v1 は6番目、v2 は10番目)。`NORMAL` / `WARNING` / `ALERT` / `CRITICAL` 以外は、最も低い優先度にします。避難所コードなど、ほかの欄に `CRITICAL` という文字列があっても、優先されません(`status` を持たない古い行だけ、従来どおり文字列の検索で判定します)

### 送信

- 送る順番: 送ってよい時刻(`next_attempt_at`)になった行を、緊急度順(CRITICAL → ALERT → WARNING → その他)、同じ緊急度では `hub_received_at` 順、次に `id` 順
- リクエスト: `POST`、`{"packet": "<raw packet>", "hub_received_at": "<UTC>"}`、ヘッダー `X-Gateway-Key`(環境変数 `TSUNAGU_GATEWAY_API_KEY`。未設定なら起動時にエラーで終了)
- リダイレクトは追いません

### 応答の扱い

| 応答 | 扱い | 後続の Packet |
|---|---|---|
| 2xx | キューから削除 | 送る |
| 400・422 | **隔離**(`quarantined_packets` へ移し、再送しない) | 送る |
| 403 + `PACKET_AUTH_FAILED` | その Packet だけ**隔離** | 送る |
| 409 | **隔離**し、ログに残す | 送る |
| 401、403(それ以外)、3xx、そのほかの想定外の応答(404 など) | 設定異常として**送信を停止**。キューは保持し、受信とキューへの保存は続ける | 送らない |
| 429・5xx | その行に指数バックオフ(5秒から上限5分、ジッタ付き)を設定 | 送る。ただし同じ周回で 429・5xx が3件続いたら、その周回は止める |
| 接続エラー・タイムアウト | 行はそのまま | その周回は止め、次の周回(約5秒後)で再開 |

- 以前は、4xx の Packet がキューに残り、5秒ごとに再送され続けていました。いまは 400・422・403(`PACKET_AUTH_FAILED`)・409 を隔離するので、再送され続けません
- 送信の停止は、ログに原因(`HTTP_401` など)とともに出します。同じログは5分ごとに間引きます。**再開は、ゲートウェイの再起動のとき**です
- ログには、Packet の内容(v2 の最後の hmac 欄を含む)と Gateway Key を出しません。Packet は `id` の先頭、版、`status`、長さだけで示します

### 隔離テーブル(`quarantined_packets`)

列: `packet`(署名つきの raw packet をそのまま保存)、`hub_received_at`、`reason_code`(`detail.code` か `HTTP_<状態>`)、`http_status`、`response_summary`(応答の要約。200文字まで。Gateway Key と hmac は伏せる)、`quarantined_at`

### キューのファイルの扱い(重要)

- キューと隔離テーブルの SQLite のファイルには、**署名つきの Packet** が入ります
- ファイルを、他人に渡す・GitHub に載せる・チャットに貼ることは避けてください
- ハブPCを紛失したときに備えて、ディスクの暗号化(BitLocker など)と、OSのログイン(パスワードやPIN)を設定してください。紛失したときは、その端末の鍵を、サーバー側で無効化(`PACKET_DISABLED_DEVICES`)するか、作り直すことを検討してください
- 隔離テーブルの保存期間と削除は、今回は対象外です(将来の課題)。必要に応じて、手で削除してください

### 隔離した Packet を再送する手順

サーバー側の鍵台帳を直したあと(例: `PACKET_AUTH_FAILED` で隔離された Packet)に、隔離した Packet をキューへ戻す手順です。専用のコマンドはありません。

1. ゲートウェイを止める(Ctrl + C)
2. キューのファイルをバックアップする(例: `.tsunagu/lora_gateway_queue.db` をコピー。コピーも上の注意どおりに扱う)
3. 戻す Packet を確認する。Packet の内容は画面に出さず、件数と理由だけを見る

```powershell
python -c "import sqlite3; c = sqlite3.connect('.tsunagu/lora_gateway_queue.db'); print(c.execute('SELECT reason_code, count(*) FROM quarantined_packets GROUP BY reason_code').fetchall())"
```

4. 理由を指定して、キューへ戻す。下の例は `PACKET_AUTH_FAILED` です。キューと同じ id の作り方で戻し、戻した行を隔離テーブルから消します(リポジトリの直下で、PowerShell で実行)

```powershell
@'
import hashlib, sys, time
sys.path.insert(0, "tools")
import lora_serial_gateway as g

QUEUE_DB = ".tsunagu/lora_gateway_queue.db"
REASON = "PACKET_AUTH_FAILED"

q = g.PacketQueue(g.Path(QUEUE_DB))
rows = q.connection.execute(
    "SELECT id, packet, hub_received_at FROM quarantined_packets WHERE reason_code = ?", (REASON,)
).fetchall()
with q.connection:
    for row_id, packet, hub_received_at in rows:
        q.connection.execute(
            "INSERT OR IGNORE INTO pending_packets"
            " (id, packet, queued_at, status, hub_received_at, attempts, next_attempt_at)"
            " VALUES (?, ?, ?, ?, ?, 0, 0)",
            (hashlib.sha256(packet.encode("utf-8")).hexdigest(), packet, time.time(),
             g.extract_status(packet), hub_received_at),
        )
        q.connection.execute("DELETE FROM quarantined_packets WHERE id = ?", (row_id,))
print("requeued", len(rows))
'@ | python -
```

5. ゲートウェイを起動する。戻した Packet は、受信時刻(`hub_received_at`)を保ったまま、緊急度順に送られます。サーバーはクラウド側と同じく、同じ Packet の再送を冪等に受理します

`--queue-db` を変えている場合は、パスを読み替えてください。

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
- 不正な Packet は 400 になり、ゲートウェイの隔離テーブルへ移って、再送されない。
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
