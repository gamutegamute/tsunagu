# Emergency Packet v2(バックエンド)

`POST /api/emergency-packets` が受け付ける Emergency Packet v2 の仕様と、サーバー側の扱いをまとめます。
T-Beam のファーム、ゲートウェイ、フロントの対応は別のPRで行います。

## 形式

```text
v2|device_id|key_id|install_id|sequence|reported_at|shelter_code|people_count|water_stock|status|request_code|hmac
```

| フィールド | 形式 |
|---|---|
| `device_id` | 英大文字・数字の5文字 |
| `key_id` | 英大文字の16進2文字 |
| `install_id` | 英大文字の16進16文字 |
| `sequence` | 英大文字の16進8文字 |
| `reported_at` | 10進のUnix秒(UTC) |
| `shelter_code` | 3〜12文字(英大文字・数字・`_`・`-`) |
| `people_count` / `water_stock` | 0〜1,000,000の整数(数字のみ。符号・空白は不可) |
| `status` | `NORMAL` / `WARNING` / `ALERT` / `CRITICAL` |
| `request_code` | `REQ_WATER` / `REQ_MEDICAL` / `REQ_FOOD` / `REQ_RESCUE` / `REQ_CONFIRM` / `NONE` |
| `hmac` | 小文字16進32文字 |

リクエスト本文:

```json
{"packet": "v2|...", "hub_received_at": "2026-10-06T12:00:00Z"}
```

`hub_received_at`(ゲートウェイがPacketを受信した時刻)は任意です。省略するとサーバーの受信時刻を使います。

## HMAC

- HMAC-SHA256 の先頭16バイトを、小文字16進32文字にしたもの
- 署名対象は、最後の `|` より前の全体(`v2|` から `request_code` まで。区切りの `|` を含み、末尾の `|` と `hmac` は含まない)。ASCII のバイト列として計算する
- 鍵は端末ごとに別。`device_id` と `key_id` で引く
- 比較は定数時間比較(`hmac.compare_digest`)

### テストベクトル

ファーム側の実装と一致を確認するための値です。**鍵はテスト専用のダミー値**で、実機には使いません。
`backend/tests/test_emergency_packet.py` の `test_hmac_test_vector` と同じ値です。

| 項目 | 値 |
|---|---|
| 鍵(16進、32バイト) | `000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f` |
| 署名対象 | `v2\|TB001\|01\|A1B2C3D4E5F60718\|0000002A\|1791234567\|AIT001\|170\|18\|WARNING\|REQ_WATER` |
| HMAC-SHA256(全体) | `c23c0c17326995159c0cc9dfafe7fd8ca051e40005cd7ea048d6a94cd267f652` |
| `hmac`(先頭16バイト) | `c23c0c17326995159c0cc9dfafe7fd8c` |

完成したPacket:

```text
v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER|c23c0c17326995159c0cc9dfafe7fd8c
```

OpenSSL での確認:

```sh
printf '%s' 'v2|TB001|01|A1B2C3D4E5F60718|0000002A|1791234567|AIT001|170|18|WARNING|REQ_WATER' \
  | openssl dgst -sha256 -mac HMAC -macopt hexkey:000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
```

## 端末台帳と鍵

鍵はGit管理外で渡します。リポジトリには、ダミー値の `.env.example` だけを置きます。

| 環境変数 | 内容 |
|---|---|
| `PACKET_DEVICE_KEYS` | 端末台帳のJSON: `{"TB001": {"01": "<鍵の16進>"}}` |
| `PACKET_DEVICE_KEYS_FILE` | 同じ形式のJSONファイル(秘密情報ファイル)のパス。`PACKET_DEVICE_KEYS` と同時には指定できない |
| `PACKET_DISABLED_DEVICES` | 無効化する `device_id` のカンマ区切り |

- 鍵は16進で16バイト以上。台帳の形式が不正な場合、起動時(`validate_runtime_settings`)にエラーになります。実行中に不正になった場合、v2 Packet は 503 になります
- 鍵の値は、ログ・レスポンス・例外メッセージに出しません
- 端末を無効化すると、その端末のPacketは 403 になり、監査ログの理由が `DEVICE_DISABLED` になります(台帳から消した場合は `UNKNOWN_DEVICE`)

## 受信処理とエラー

処理順: Gateway Key 確認 → 形式検証 → 端末・鍵の確認とHMAC検証 → 保存

| 状況 | HTTP | `detail.code` |
|---|---|---|
| Gateway Key が不正 | 401 | (従来どおり) |
| 形式不正(区切り数・長さ・文字・範囲)。HMAC検証より前に判定 | 400 | `PACKET_FORMAT_INVALID` |
| v1 で `ALLOW_V1_PACKETS=false` | 400 | `PACKET_VERSION_DISABLED` |
| 不明 `device_id`・無効な端末・不明 `key_id`・HMAC不一致 | 403 | `PACKET_AUTH_FAILED` |
| 同一キー・内容違い | 409 | `PACKET_DUPLICATE_CONFLICT` |
| 新規、または同一キー・同一内容の再送 | 201 | — |

- 401(Gateway Key)と403(Packet認証)を分けているのは、ゲートウェイが偽Packet1通のせいでAPIへの送信全体を止めないようにするためです
- 403 のPacketは、`CRITICAL` でも `emergency_packets` / `observations` に保存しません。本文は監査ログ `packet_security_events` に `PACKET_AUTH_FAILED` として記録します。失敗理由(`UNKNOWN_DEVICE` / `DEVICE_DISABLED` / `UNKNOWN_KEY_ID` / `HMAC_MISMATCH`)は監査ログにだけ残し、レスポンスには出しません
- 409 のときは既存の行を上書きせず、`packet_security_events` に `PACKET_DUPLICATE_CONFLICT` として記録します

## 重複判定

- **v2**: 重複判定キーは `(device_id, install_id, sequence)` です(DBの一意制約 `emergency_packets_device_install_sequence_key`)
  - 同一キー・同一内容(`raw_packet` が完全一致)は再送として扱い、既存の行を 201 で返します(v1の再送と同じ)
  - 同一キー・内容違いは 409 です
  - 到着順は問いません(`sequence` の大小は見ない)
- **v1**: 従来の仕組みのままです。v1 には端末側の識別子が無いため、**サーバーの受信時刻を10秒のウィンドウに丸めたものと `raw_packet` で重複を判定します**(`EMERGENCY_PACKET_DEDUP_WINDOW_SECONDS`)。`hub_received_at` はこの判定に使いません

## 時刻

`emergency_packets` に、次を別の列として保存します。

| 列 | 内容 |
|---|---|
| `reported_at` | 端末が報告した時刻(Packet内の値) |
| `hub_received_at` | ゲートウェイの受信時刻(リクエストで指定、無ければサーバーの受信時刻) |
| `cloud_synced_at` | クラウドへの同期時刻。列だけ用意し、値は Outbox(後のPR)で入れる |
| `received_at` | APIサーバーが行を作った時刻(従来の列) |

`reported_at` と `hub_received_at` の差が600秒を超えたら `time_trust=UNTRUSTED` にします(拒否はしません)。
このとき、ダッシュボード用の `observations.observed_at` には `hub_received_at` を使います。それ以外(`TRUSTED`)は `reported_at` を使います。

既存の `packet_time` 列(NOT NULL)には、互換のため `reported_at` を JST の `HH:MM` にした値を入れます。

## 署名の状態(`signature_status`)

`emergency_packets.signature_status` と `observations.signature_status` に保存します。

| 値 | 意味 |
|---|---|
| `SIGNATURE_VALID` | v2 で HMAC 検証に成功 |
| `UNSIGNED_V1` | v1(署名なし)。認証済みの報告としては扱わない |
| NULL | この列を追加する前の行、Webからの報告 |

既存の `verification_status`(`UNVERIFIED` / `VERIFIED` / `REJECTED`)は本部職員による確認の状態で、署名とは別物です。
HMAC が正しくても `verification_status` は自動で `VERIFIED` にせず、従来どおり `UNVERIFIED` で作ります。

## v1 の切り替え(`ALLOW_V1_PACKETS`)

- コード上のデフォルトは `false`。v1 は 400 + `PACKET_VERSION_DISABLED` で拒否します
- 開発用の `docker-compose.yml` と `.env.example` では `true` です
- `true` のときも、v1 は `signature_status=UNSIGNED_V1` として保存し、v2 の署名済みの報告とは区別します

## インシデント昇格に備えて保存しているもの

`emergency_packets` の1行から、次を後から参照できます。

- 元の Packet: `raw_packet`
- 反映先の観測: `observation_id`(`observations.id`。避難所が不明な場合は NULL)
- `device_id` / `key_id` / `install_id` / `sequence`
- `reported_at` / `hub_received_at` / `time_trust`
- 認証結果: `signature_status`

## DB移行(`0004_emergency_packet_v2`)

- `emergency_packets` に上記の列を追加し、`(device_id, install_id, sequence)` の一意制約を追加
- `observations.signature_status` を追加
- 監査ログ用の `packet_security_events` テーブルを追加
- 追加した列はすべて NULL を許可します。既存の v1 の行は NULL のまま動きます(一意制約もNULLの行には効きません)
