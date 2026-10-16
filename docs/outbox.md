# クラウドへの配送(Outbox)

ローカルサーバーで受理した Emergency Packet v2 を、クラウドへ配送する仕組みと、配送状況を読むAPIの契約です。
本部画面の実装は、このページの契約を使います。

- 配送は、ローカルからクラウドへの**一方向のみ**です。クラウドからローカルへの書き戻しはしません
- クラウド側は、重複判定キー `(device_id, install_id, sequence)` で同じ報告の再送を既存の行として受理します(冪等)。応答が失われたときの再送は安全です
- 受信APIの形とエラー応答は `docs/emergency-packet-v2.md` が正です

> この文書の動作は、PC上のテスト(クラウドを `httpx.MockTransport` で模擬)で確認しています。実際のクラウド環境・衛星回線では確認していません。

## 全体の流れ

```text
T-Beam → ゲートウェイ → ローカルAPI(POST /api/emergency-packets)
                           │ 受理と同じトランザクションで、宛先ごとに delivery_outbox へ登録
                           ▼
                    outbox-worker(python -m app.outbox_worker)
                           │ 宛先ごとに1件ずつ、緊急度順に POST
                           ▼
                    クラウドの受信API(POST {base_url}/api/emergency-packets)
```

## 設定

| 環境変数 | デフォルト | 内容 |
|---|---|---|
| `OUTBOX_ENABLED` | `false` | `true` のときだけ、登録とワーカーが動く |
| `OUTBOX_DESTINATIONS` | (空) | 宛先の一覧(JSON)。空なら何もしない |
| `OUTBOX_BATCH_SIZE` | `10` | 1周で、1つの宛先に送る最大件数 |
| `OUTBOX_HTTP_TIMEOUT_SECONDS` | `10` | HTTPのタイムアウト |
| `OUTBOX_LEASE_SECONDS` | `60` | 送信中(SENDING)の行を、ワーカーが落ちたとみなして PENDING に戻すまでの時間 |
| `OUTBOX_PROBE_INTERVAL_SECONDS` | `30` | 疎通確認(プローブ)の間隔 |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2` | ワーカーの周回の間隔 |
| `OUTBOX_STATUS_DOWN_SECONDS` | `120` | 状態判定: DOWN のしきい値 |
| `OUTBOX_STATUS_DELAYED_LATENCY_MS` | `5000` | 状態判定: DELAYED の遅延のしきい値 |
| `OUTBOX_STATUS_DELAYED_PENDING_SECONDS` | `60` | 状態判定: DELAYED の、最古の未送信のしきい値 |

**数値のデフォルトは、すべてデモ用の暫定値です。** 実際の回線(衛星回線など)に合わせて見直してください。

宛先の例:

```json
[{"id": "cloud-sat", "base_url": "https://example.invalid", "key_env": "OUTBOX_KEY_CLOUD_SAT"}]
```

- `id`: 英小文字・数字・`_`・`-`(先頭は英小文字か数字、63文字まで)。宛先ごとに一意
- `base_url`: `http` または `https` のURL。受信APIは `{base_url}/api/emergency-packets`、プローブは `{base_url}/health`。書式は次のとおりです
  - 許可: スキーム(`http` / `https`)、ホスト(必須)、ポート、**ベースのパス**(例: `https://example.invalid/tsunagu`。リバースプロキシの下に置く場合など)
  - 拒否: ユーザー名・パスワード(`user:pass@`)、クエリ(`?`)、フラグメント(`#`)
  - パスの各セグメントに使える文字は、英数字と `.` `_` `~` `-` だけです。空のセグメント(`//`)、`.` と `..`、`%`(`%2e%2e` や `%2f` による回避を防ぐため)、空白・制御文字・`\`・ASCII以外の文字は拒否します
  - 末尾のスラッシュは1つだけ取り除いて保存します(`https://example.invalid/tsunagu/` は `https://example.invalid/tsunagu` として扱い、`//` にはなりません)
- `key_env`: その宛先のGateway Keyを入れた**環境変数の名前**。宛先ごとに別の鍵です。鍵の値はDB・ログ・APIのレスポンスに出しません
- 書式が不正なら、APIとワーカーの起動時にエラーになります。エラーメッセージには、拒否した理由の種類(認証情報、クエリ・フラグメント、パス、スキーム・ホスト)だけを出し、**鍵の値やURLの値は出しません**
- APIは宛先の鍵を持ちません(書式だけ確認します)。鍵を読むのはワーカーだけで、鍵の環境変数が無ければワーカーの起動時にエラーになります
- 宛先のURLをログに出すときは、クレデンシャル(`user:pass@`)とクエリ・フラグメントを伏せます。httpx/httpcore のログ(送信先のURLをそのまま出す)は WARNING 以上に絞っています

docker compose(デモ用):

```sh
cp .env.example .env   # 値はダミー。実際の鍵は .env にだけ書く(Git管理外)
docker compose --profile demo up
```

`outbox-worker` サービスは `profiles: ["demo"]` で、`api` と同じDockerfileのイメージです。宛先を足したら、その `key_env` と同じ名前の変数を `docker-compose.yml` の `outbox-worker` の `environment` にも足してください。

## 登録

- 登録するのは、ローカルで受理した **v2 の `signature_status=SIGNATURE_VALID` の報告だけ**です。v1(`UNSIGNED_V1`)は転送しません(クラウドが v1 を拒否するため)
- 報告の受理と**同じトランザクション**で、宛先ごとに `delivery_outbox` へ `PENDING` で登録します(`UNIQUE (emergency_packet_id, destination_id)` と `ON CONFLICT DO NOTHING`)
- 同じ報告の再送(既存の行が返る場合)では、行を重複して作りません。前回の登録が失敗していた場合は、再送のときに登録されます
- 登録は SAVEPOINT の中で行います。**登録が失敗しても、報告の受理は失敗させません**(登録だけを取り消し、ログに残します)

### v1 が転送されないことの見分け方

`GET /api/emergency-packets/{id}/deliveries` の `forwardable` が `false` で、`signature_status` が `UNSIGNED_V1` です。`deliveries` は空です。
一覧(`GET /api/emergency-packets`)では、`signature_status` が `SIGNATURE_VALID` でない行は配送の対象外です。

### 登録の失敗の検知

1. ログ: `Outbox registration failed for packet_id=<id>: <例外の種類>`(ERROR)
2. DB: 次のクエリで、配送の対象なのに登録されていない報告が分かります(宛先ごとに確認)

```sql
SELECT p.id, p.received_at
FROM emergency_packets p
WHERE p.signature_status = 'SIGNATURE_VALID'
  AND NOT EXISTS (
    SELECT 1 FROM delivery_outbox o
    WHERE o.emergency_packet_id = p.id AND o.destination_id = 'cloud-sat'
  )
ORDER BY p.received_at;
```

`OUTBOX_ENABLED` を `true` にする前に受理した報告も、このクエリに出ます。自動ではさかのぼって登録しないので、`backfill` で登録します(下の「登録が欠けた報告の登録(backfill)」)。

## ワーカー

```sh
python -m app.outbox_worker                 # ループ
python -m app.outbox_worker once            # 1周だけ
python -m app.outbox_worker requeue --destination <id> --error-code <コード>
python -m app.outbox_worker resume --destination <id>
python -m app.outbox_worker backfill --destination <id> (--since <ISO8601> | --all) [--dry-run]
```

1周の処理(`run_once`)。**時刻は、使う時点ごとに取り直します**(HTTPが遅くても、記録する時刻が実際の時刻からずれないようにするため)。`lease_until` と `last_attempt_at` は行を取った時点、`accepted_at` と `next_attempt_at`(バックオフ)は応答を受けた時点を基準にします。`delivery_attempts.attempted_at` は、送信を始めた時刻です。テストでは `run_once(clock=...)` で時計を渡せます(`run_once(now)` は、その時刻に固定した時計になります):

1. `lease_until` を過ぎた `SENDING` の行を `PENDING` に戻す(`last_error_code=LEASE_EXPIRED`)。送信済みかは分からないが、クラウドは冪等なので送り直してよい
2. 宛先ごとに、順番に(同時送信なし):
   1. プローブの間隔が過ぎていれば、`GET {base_url}/health` を**鍵なし**で呼び、`delivery_attempts` に `kind=PROBE` で記録する。`STOPPED` の宛先でもプローブは続ける
   2. 宛先が止まっていれば(`STOPPED` の行がある)、送らない
   3. 期限の来た `PENDING` の行を、**緊急度順**(CRITICAL → ALERT → WARNING → その他)、同じ緊急度では **`hub_received_at` 順**に、`OUTBOX_BATCH_SIZE` 件まで、1件ずつ送る。行は `SELECT ... FOR UPDATE SKIP LOCKED` で取り、`SENDING` にして `lease_until` を設定する

送信の内容:

- `POST {base_url}/api/emergency-packets`、本文は `{"packet": "<受け取った文字列そのまま>", "hub_received_at": "<ISO 8601>"}`
- ヘッダー `X-Gateway-Key` に、その宛先の鍵を付ける
- **リダイレクトは追わない**(別のホストへ鍵を送らないため)

### 応答の扱い

| 応答 | 行の状態 | 宛先 | `last_error_code` |
|---|---|---|---|
| 2xx | `ACCEPTED`(`accepted_at` を記録し、`emergency_packets.cloud_synced_at` を更新) | 続ける | なし |
| 400・422 | `QUARANTINED`(再送しない) | 続ける | `detail.code`(例: `PACKET_FORMAT_INVALID`)か `HTTP_400` / `HTTP_422` |
| 401 | `STOPPED` | **止める** | `HTTP_401` |
| 403 + `PACKET_AUTH_FAILED` | `QUARANTINED`(この行だけ) | 続ける | `PACKET_AUTH_FAILED` |
| 403(それ以外) | `STOPPED` | **止める** | `HTTP_403` |
| 409 | `QUARANTINED`(ログに残す) | 続ける | `detail.code`(例: `PACKET_DUPLICATE_CONFLICT`)か `HTTP_409` |
| 429・5xx | `PENDING`(バックオフ) | 同じ宛先の次の行へ進む | `HTTP_429` / `HTTP_5xx` |
| 通信断 | `PENDING`(バックオフ) | **その宛先の今回の周回を止める** | `NETWORK_ERROR` |
| タイムアウト | `PENDING`(バックオフ) | **その宛先の今回の周回を止める** | `TIMEOUT` |
| 上のどれでもない(3xx、404 など) | `STOPPED` | **止める**(設定異常とみなす。安全側) | `HTTP_<状態>` |

- バックオフ: `5秒 × 2^(試行回数-1)`、上限5分。ジッタは、その半分から全体の間でばらつかせる
- 宛先を止める(`STOPPED`)のは、鍵やURLの設定異常のときです。ログに `Outbox destination STOPPED (configuration error: gateway key or URL)` と出ます。その宛先の `PENDING` の行は、**消さずに保持**し、送らずに止めます
- `cloud_synced_at` は、複数の宛先がある場合、最初にクラウドへ届いた時刻です
- 各試行は `delivery_attempts` に記録します(`kind`、`attempted_at`、`outcome`、`http_status`、`latency_ms`、`error_code`)。`outcome` は、配送が `ACCEPTED` / `QUARANTINED` / `STOPPED` / `RETRY`、プローブが `PROBE_OK` / `PROBE_FAILED` です
- 応答の本文そのものは、DB・ログに残しません(`detail.code` だけを取り出します)

### 復旧

- クラウド側の鍵台帳を直したあと(例: `PACKET_AUTH_FAILED` で隔離された報告): `python -m app.outbox_worker requeue --destination <id> --error-code PACKET_AUTH_FAILED`。指定した宛先・エラーコードの `QUARANTINED` を `PENDING` に戻します
- 宛先の鍵やURLを直したあと: `python -m app.outbox_worker resume --destination <id>`。その宛先の `STOPPED` の行を `PENDING` に戻し、送信を再開します
- どちらも、実行内容と件数をログに残します(`Outbox requeue: destination=... error_code=... requeued=N`、`Outbox resume: destination=... resumed=N`)

### 登録が欠けた報告の登録(backfill)

`delivery_outbox` に行が無い報告は、あとから Outbox を有効にしても、クラウドへ届きません。次の場面で `backfill` を使います。

| 場面 | 理由 |
|---|---|
| Outbox を後から有効にしたとき | `OUTBOX_ENABLED=false` の間や、宛先を設定する前に受理した報告は登録されていない |
| 宛先を追加したとき | 追加する前に受理した報告には、新しい宛先の行が無い |
| 登録の失敗を検知したとき | 登録に失敗した報告(ログ `Outbox registration failed`)は、同じ報告が再送されない限り登録されない |

```sh
# 1. 対象の件数だけを確認する(登録しない)
python -m app.outbox_worker backfill --destination cloud-sat --since 2026-10-06T09:00:00+09:00 --dry-run
# 2. 登録する
python -m app.outbox_worker backfill --destination cloud-sat --since 2026-10-06T09:00:00+09:00
```

- 対象: `signature_status=SIGNATURE_VALID` の v2 の報告のうち、指定の宛先の `delivery_outbox` の行が無いもの。v1 は対象外です
- `--since`: `hub_received_at` が指定時刻**以降**(ちょうどを含む)の報告だけを対象にします。タイムゾーン(`Z` や `+09:00`)を必ず付けてください(付けないとエラー)
- `--all`: 時刻で絞らず、すべてを対象にします
- `--since` と `--all` のどちらも無いときは、エラーにします。**古いデモデータを、うっかりクラウドへ送らないため**です。デモリセットの前のデータなどを送りたくないときは、`--since` で範囲を絞ってください
- `OUTBOX_DESTINATIONS` に無い宛先を指定すると、エラーで終了します
- 登録は `PENDING`、`next_attempt_at` は実行した時刻です。`ON CONFLICT DO NOTHING` なので冪等です(2回実行すると、2回目は0件)。既存の行(`ACCEPTED` など)は変更しません
- ログと出力には、件数だけを出します(Packet の内容は出しません)。例: `Outbox backfill: destination=cloud-sat since=2026-10-06T09:00:00+09:00 registered=3`
- 登録した行は、ワーカーが通常どおり緊急度順に配送します。`OUTBOX_ENABLED` が `true` でないときは、警告を出して登録だけを行います(有効にしたあとで配送されます)

## 読み取りAPI(本部のみ)

どちらも本部のログインが必要です(未ログインは 401、本部以外は 403)。

### `GET /api/destinations/status`

```json
{
  "enabled": true,
  "generated_at": "2026-10-06T12:00:00Z",
  "destinations": [
    {
      "destination_id": "cloud-sat",
      "configured": true,
      "state": "DELAYED",
      "last_success_at": "2026-10-06T11:59:40Z",
      "last_reachable_at": "2026-10-06T11:59:55Z",
      "last_latency_ms": 6200,
      "queue_depth": 3,
      "sending_count": 0,
      "stopped_count": 0,
      "oldest_pending_at": "2026-10-06T11:58:30Z",
      "accepted_count": 120,
      "quarantined_count": 1,
      "quarantined_by_error_code": {"PACKET_AUTH_FAILED": 1},
      "last_error_code": "HTTP_503",
      "last_error_at": "2026-10-06T11:59:10Z"
    }
  ]
}
```

| 項目 | 意味 |
|---|---|
| `enabled` | `OUTBOX_ENABLED` の値 |
| `configured` | 現在の設定にある宛先か。設定から外した宛先でも、行が残っていれば `false` で表示する |
| `last_success_at` | 配送が最後に成功(`ACCEPTED`)した時刻 |
| `last_reachable_at` | プローブ(`PROBE_OK`)または配送(`ACCEPTED`)が最後に成功した時刻 |
| `last_latency_ms` | 直近の試行(配送・プローブ)の遅延 |
| `queue_depth` | `PENDING` の件数(宛先が止まっている間も、保持している行を数える) |
| `sending_count` / `stopped_count` | `SENDING` / `STOPPED` の件数 |
| `oldest_pending_at` | 未送信(`PENDING`・`SENDING`)のうち、最も古い行の登録時刻 |
| `quarantined_count` / `quarantined_by_error_code` | 隔離(`QUARANTINED`)の件数と、エラーコード別の件数 |
| `last_error_code` / `last_error_at` | 直近の配送エラーのコードと時刻 |

`state` の判定(上から順に):

| `state` | 条件 |
|---|---|
| `AUTH_ERROR` | 宛先が止まっている(`STOPPED` の行がある) |
| `UNKNOWN` | 配送の試行もプローブも、まだ1回もない |
| `DOWN` | 最後のプローブまたは配送の成功から `OUTBOX_STATUS_DOWN_SECONDS`(120秒)を超えている。試行があるのに一度も成功していない場合も含む |
| `DELAYED` | 直近の遅延が `OUTBOX_STATUS_DELAYED_LATENCY_MS`(5000 ms)を超える、または最古の未送信が `OUTBOX_STATUS_DELAYED_PENDING_SECONDS`(60秒)を超えている |
| `NORMAL` | 上のどれでもない |

しきい値は、デモ用の暫定値です。

### `GET /api/emergency-packets/{id}/deliveries`

```json
{
  "emergency_packet_id": "EP-1a2b3c4d5e6f7a8b",
  "version": "v2",
  "signature_status": "SIGNATURE_VALID",
  "forwardable": true,
  "deliveries": [
    {
      "destination_id": "cloud-sat",
      "state": "ACCEPTED",
      "attempts": 2,
      "next_attempt_at": "2026-10-06T11:59:05Z",
      "last_attempt_at": "2026-10-06T11:59:10Z",
      "last_error_code": null,
      "last_error_summary": null,
      "accepted_at": "2026-10-06T11:59:10Z",
      "created_at": "2026-10-06T11:59:00Z",
      "history": [
        {"attempted_at": "2026-10-06T11:59:00Z", "outcome": "RETRY", "http_status": 503, "latency_ms": 820, "error_code": "HTTP_503"},
        {"attempted_at": "2026-10-06T11:59:10Z", "outcome": "ACCEPTED", "http_status": 201, "latency_ms": 640, "error_code": null}
      ]
    }
  ]
}
```

- 報告が無ければ 404
- `forwardable=false` のとき(v1 など)は、`deliveries` は空です
- 行の `state` は `PENDING` / `SENDING` / `ACCEPTED` / `QUARANTINED` / `STOPPED`

既存の一覧API(`GET /api/emergency-packets` など)のレスポンスは変更していません。

## DB(Alembic `0005_delivery_outbox`)

- `delivery_outbox`: `id`、`emergency_packet_id`(`emergency_packets` への外部キー)、`destination_id`、`state`、`attempts`、`next_attempt_at`、`lease_until`、`last_attempt_at`、`last_error_code`、`last_error_summary`、`accepted_at`、`created_at`。`UNIQUE (emergency_packet_id, destination_id)`
- `delivery_attempts`: `id`、`outbox_id`(プローブは NULL)、`destination_id`、`kind`(`DELIVERY` / `PROBE`)、`attempted_at`、`outcome`、`http_status`、`latency_ms`、`error_code`
- `emergency_packets` / `observations` には、配送状態の列を足していません(1件の報告に、宛先ごと・試行ごとの履歴を残すため)
- デモリセット(`TRUNCATE ... CASCADE`)では、配送の行と履歴も消えます
