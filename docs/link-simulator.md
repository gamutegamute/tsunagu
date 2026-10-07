# 回線障害のモック(link simulator)

> **設定値とプリセットは試験用です。Starlink など、実際の衛星回線の実測性能ではありません。実衛星では検証していません。**

`tools/link_simulator.py` は、Outboxのワーカーとクラウドの受信APIのあいだに挟み、遅延・帯域・欠落・瞬断を再現する、試験用のHTTP中継サーバーです。標準ライブラリだけで動きます。パケットの中身は改変しません。

```text
Outboxのワーカー(python -m app.outbox_worker)
        │ POST /api/emergency-packets、GET /health
        ▼
本モック(tools/link_simulator.py、--listen)  ← 制御用(--control): 設定の変更、down/up、統計
        │ 遅延・帯域・欠落・瞬断を再現して転送
        ▼
クラウドの受信API(--upstream)
```

## 使い方

```sh
python tools/link_simulator.py --upstream https://example.invalid \
    --listen 127.0.0.1:8090 --control 127.0.0.1:8091 [--seed N] [--config file.json] [--preset NAME]
```

| オプション | 内容 |
|---|---|
| `--upstream` | **必須**(デフォルトなし)。転送先はこのURLだけです。Gateway Key を意図しない宛先へ送らないため、デフォルトを持ちません。クレデンシャル(`user:pass@`)・クエリ・フラグメントを含むURLは受け付けません |
| `--listen` | 中継の待ち受け(デフォルト `127.0.0.1:8090`)。`127.0.0.1` 以外(`0.0.0.0` など)を指定すると、ほかの機器から見えるので、警告を出します |
| `--control` | 制御用の待ち受け(デフォルト `127.0.0.1:8091`)。**`127.0.0.1` 以外はエラーで終了**します |
| `--seed` | 乱数の種。同じ seed・同じ設定なら、同じ順で同じ結果になります |
| `--config` | 設定のJSONファイル。`--preset` の上に重ねて適用します |
| `--preset` | 設定のひな形(下記) |

Outboxのワーカーの宛先は、`base_url` をモックに向けます(例: `{"id": "cloud-sat", "base_url": "http://127.0.0.1:8090", "key_env": "OUTBOX_KEY_CLOUD_SAT"}`)。

### 中継の決まり

- 転送先は、起動時の `--upstream` だけです。リクエスト行の絶対URLや `Host` ヘッダーは無視し、**パスとクエリだけ**を転送します(`--upstream` にパスがあれば、その後ろにつなげます)
- 転送するヘッダーは、`Content-Type`、`Accept`、`Accept-Encoding`、`Accept-Language`、`User-Agent`、`X-Gateway-Key` だけです(許可したものだけ)。`Connection`、`Transfer-Encoding`、`Upgrade` などの hop-by-hop のヘッダーは転送しません
- 応答は、hop-by-hop のヘッダーを除いて、そのまま返します。**リダイレクトは追わず**、3xx をそのまま返します
- リクエストの本文は最大 64KB です。超えたら 413 を返します。`Transfer-Encoding: chunked` の本文は受け付けず、411 を返します
- 上流に届かないときは 502 を返します(統計の `upstream_error`)

## 設定項目

| 項目 | 範囲 | 内容 |
|---|---|---|
| `delay_ms` | 0〜600000 | 転送前の遅延 |
| `jitter_ms` | 0〜600000 | 遅延の揺らぎ。遅延 = `delay_ms` ± `jitter_ms`(0未満にはしない) |
| `drop_request_rate` | 0〜1 | リクエストを上流へ転送せずに失敗させる割合 |
| `drop_response_rate` | 0〜1 | 上流へ転送し、上流が処理したあとに、**応答だけ**を破棄して接続を切る割合 |
| `drop_mode` | `reset` / `hang` | 失敗のさせ方。`reset` は接続を即座に切る。`hang` は応答せずに待つ(クライアントのタイムアウトを起こす) |
| `hang_seconds` | 0〜3600 | `hang` で待つ最大時間(デフォルト30秒) |
| `bandwidth_kbps` | 0〜10000000 | 帯域の上限。リクエスト本文と応答本文のサイズから転送時間を計算して待つ(0なら無制限) |
| `down` | true / false | true の間は、すべて失敗させる(方式は `drop_mode`) |
| `down_for_seconds` | 0〜86400 | 指定した秒数だけ down にして、自動で復旧する |

- 範囲外・不明なキー・型の違う値は拒否します(400)
- 実行中の変更は、次のリクエストから反映します

### hang の挙動

- `drop_mode=hang` のときは、応答を返さずに待ちます。待つ時間の上限は `hang_seconds` です。上限に達したら、応答せずに接続を閉じます(ログ `event=hang_end reason=timeout`)
- クライアントが先に切断したら(タイムアウトなど)、0.1秒ごとに確かめているので、すぐに待つのをやめます(`reason=client_closed`)
- モックを止めたとき(Ctrl+C)は、hang 中のリクエストも、遅延の待ちも、すぐに終わります(`reason=shutdown`)。hang 中のリクエストがあっても、停止は待たされません
- 受け付けた接続には、30秒の読み込みのタイムアウトを付けています(keep-alive で放置された接続などで、待ち続けないため)
- 本文が 64KB を超えたときは、本文を 1MiB まで読み捨ててから 413 を返して接続を閉じます(読まずに閉じると、OSが接続をリセットし、クライアントが 413 を読めないことがあるため)。1MiB を超える本文では、クライアントには接続のリセットとして見えることがあります

## プリセット

数値は、これまでの試験条件(帯域 256 kbps〜1 Mbps、遅延 500〜2,000 ms、欠落 3〜10%、瞬断 30秒〜数分)の**例**であり、**実測性能ではありません**。

| 名前 | 内容 |
|---|---|
| `clean` | 何も再現しない |
| `slow-link` | 帯域 256 kbps、遅延 500 ± 200 ms |
| `lossy-link` | 遅延 1000 ± 500 ms、`drop_request_rate` 0.05、`drop_response_rate` 0.05 |
| `very-poor-link` | 帯域 256 kbps、遅延 2000 ± 500 ms、`drop_request_rate` 0.10、`drop_response_rate` 0.10 |
| `outage-30s` | `clean` の設定で、起動直後(または preset を選んだ直後)に30秒だけ down。手動で始めるときは `POST /sim/down?seconds=30` |

## 制御用のエンドポイント(`--control`、127.0.0.1 のみ)

| メソッドとパス | 内容 |
|---|---|
| `GET /sim/config` | 現在の設定。`down_remaining_seconds` は、自動復旧までの残り秒数(手動の down なら `null`) |
| `POST /sim/config` | JSONで設定を更新する(部分更新可)。例: `{"drop_response_rate": 0.5}` |
| `POST /sim/down?seconds=N` | N秒だけ down にする。N を省略すると、`/sim/up` まで down |
| `POST /sim/up` | down を解除する |
| `POST /sim/reset` | 設定を起動時の状態に戻し、カウンターを0にし、乱数を seed から引き直す。起動時の `outage-30s` の30秒の down はやり直さない |
| `POST /sim/preset?name=NAME` | プリセットを適用する(設定を置き換える) |
| `GET /sim/stats` | 件数(`forwarded`、`dropped_request`、`dropped_response`、`down_rejected`、`delayed`、`upstream_error`、`too_large`、`length_required`)と、直近100件の遅延の平均・最大(`recent_delay_ms_avg`、`recent_delay_ms_max`) |

```sh
curl -s http://127.0.0.1:8091/sim/config
curl -s -X POST http://127.0.0.1:8091/sim/config -H "Content-Type: application/json" -d '{"drop_response_rate": 1}'
curl -s -X POST "http://127.0.0.1:8091/sim/down?seconds=30"
curl -s http://127.0.0.1:8091/sim/stats
```

(PowerShell では `curl.exe` を使うか、`Invoke-RestMethod` を使ってください。)

## ログの見方

1件ごとに1行、標準出力に出します。

```text
result=delayed delay_ms=523 upstream_status=201 request_bytes=118 response_bytes=402 elapsed_ms=1290
result=dropped_response delay_ms=1012 upstream_status=201 request_bytes=118 response_bytes=402 elapsed_ms=1030
result=dropped_request delay_ms=0 upstream_status=- request_bytes=118 response_bytes=0 elapsed_ms=0
result=down delay_ms=0 upstream_status=- request_bytes=118 response_bytes=0 elapsed_ms=0
```

- `result`: `forwarded`(遅延なしで転送)、`delayed`(遅延ありで転送)、`dropped_request`、`dropped_response`、`down`、`upstream_error`、`too_large`、`length_required`
- `delay_ms`: 再現した遅延(帯域による転送時間は含まない)。`elapsed_ms`: 受け付けてから結果が決まるまでの時間
- `upstream_status`: 上流の状態コード(上流へ送っていなければ `-`)
- `dropped_response` の行は、上流は処理済み(`upstream_status` がある)で、クライアントには応答が届いていないことを示します
- **ヘッダー(`X-Gateway-Key` を含む)、本文、パス、クエリは、ログ・統計・例外メッセージに出しません**
- `down` などのイベントは `event=down seconds=30`、`event=auto_up`、`event=reset` のように出します

## dockerのコンテナ(Outboxのワーカー)から使う

ワーカーをコンテナで動かすときは、`base_url` を `http://host.docker.internal:8090` にします。

- **確認したこと**: Windows の Docker Desktop で、モックを `--listen 127.0.0.1:8090` で起動したまま、backendのイメージ(`tsunagu-outbox-worker`)の Python から `urllib` で `http://host.docker.internal:<port>/health` に接続し、モック経由で上流の応答(200)が届きました。**bind を `0.0.0.0` に変える必要はありませんでした**
- **未確認**: Linux の Docker Engine(Docker Desktop を使わない環境)。この場合、`host.docker.internal` は既定では使えず(`--add-host=host.docker.internal:host-gateway` などが必要)、`127.0.0.1` だけで待ち受けているモックには、コンテナから届かない可能性があります。届かないときは、`--listen` を docker のブリッジのアドレスなどにする必要がありますが、そうすると**ほかの機器からも見える**ことがあるので、ファイアウォールで閉じてください(`0.0.0.0` を指定すると警告が出ます)
- **未確認**: macOS の Docker Desktop

## 試験の例

### 応答だけ失われたときに、再送しても重複しないこと

1. モックを起動し、Outboxの宛先の `base_url` をモックに向ける
2. `POST /sim/config` で `{"drop_response_rate": 1}` にする
3. ローカルAPIに v2 の報告を1件送る。ワーカーが配送すると、クラウドは受理するが、応答はワーカーに届かない(ログに `result=dropped_response`)。ワーカーは `TIMEOUT` や `NETWORK_ERROR` として、バックオフ後に再送する
4. `POST /sim/config` で `{"drop_response_rate": 0}` に戻す。再送が `ACCEPTED` になる
5. クラウド側で、同じ報告が1件だけであること(重複判定キー `(device_id, install_id, sequence)` で冪等に受理されていること)を確認する

割合を `0.3` などにすると、複数件で同じことを確かめられます。`--seed` を付けると、どの件が落ちるかを再現できます。

### 片方の宛先だけ止める

宛先ごとにモックを1つずつ起動し(ポートを変える)、止めたい宛先のモックだけを down にします。

```sh
python tools/link_simulator.py --upstream https://cloud-a.example.invalid --listen 127.0.0.1:8090 --control 127.0.0.1:8091
python tools/link_simulator.py --upstream https://cloud-b.example.invalid --listen 127.0.0.1:8092 --control 127.0.0.1:8093
curl -s -X POST "http://127.0.0.1:8093/sim/down?seconds=120"
```

止めた宛先の行は、ワーカーで `PENDING`(バックオフ)のまま保持され、もう片方の宛先は配送が進みます。

## 対象外

本部画面、Outboxの変更、docker-compose へのサービスの追加(統合テストのPRで行う)、実衛星、パケットの中身の改変。
