# 実行環境と復旧手順

## 開発環境とLAN共有（#27）

通常の `docker compose up --build` はAPIを `127.0.0.1:8000`、DBを `127.0.0.1:5432` に限定する。開発用の本部ログインと既知のDB資格情報を、共有Wi-Fiの別端末から利用できる状態にしないためである。

LANデモは明示的に `docker-compose.lan.yml` を追加する。この構成はCognito認証・固有のセッション鍵・非公開のGateway鍵・担当割当を必須にし、開発ログインとデモリセットを使わない。DBのLAN公開は追加しない。

```powershell
docker compose -f docker-compose.yml -f docker-compose.lan.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.lan.yml up --build
```

`.env` に `LAN_BIND_IP`（このPCの具体的なLAN IP）、`PUBLIC_BASE_URL`、`SESSION_SECRET`、`GATEWAY_API_KEY`、`COGNITO_DOMAIN`、`COGNITO_CLIENT_ID`、`COGNITO_ISSUER`、`AUTH_HQ_EMAILS`、`AUTH_FIELD_EMAILS`、`AUTH_SHELTER_ASSIGNMENTS` を設定する。公開URLはCognitoに登録したHTTPSのURLと一致させる。Secure Cookieを使うため、ブラウザからはHTTPSを終端するリバースプロキシ経由でアクセスする。APIのHTTPポートへの到達元は、そのプロキシ等に限定する。鍵やアカウント情報をGitへ保存しない。

別PCから既定の8000/5432ポートへ接続できないこと、LAN共有構成では未ログインの本部APIが401になること、dev-loginが404になること、許可職員だけがログインできることを配置先で確認する。実際の別PC・Cognito本番環境での確認は、今回の自動テストには含まない。

## 転送ヘッダーと匿名報告の送信制限（#28）

`TRUSTED_PROXY_CIDRS` は、APIへ接続してくるリバースプロキシの実際のIPネットワークをカンマ区切りで指定する。Terraformでは `trusted_proxy_cidrs` を使う。未指定なら `X-Forwarded-For` を無視し、実際のTCP接続元を送信制限のキーにする。

設定済みのプロキシから来た場合だけ、最大2048文字・32ホップのIPアドレス列を検証し、右側から信頼するプロキシをたどって最初の信頼外アドレスを採用する。プロキシは観測した接続元を必ず追加する必要がある。APIへ直接到達できる端末のアドレス帯を、プロキシとして許可しない。

Docker起動時のUvicornには `--no-proxy-headers` を付け、アプリが検証する前に接続元を書き換えさせない。手動起動でも同じオプションを付ける。

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

ALB経由の環境で未設定のまま使うと、匿名報告はALBの接続元ごとにまとめて制限される。配置前にALBからの実際の接続元ネットワークと、ALB以外からAPIへ到達できないことを確認して設定する。送信元キーは期限切れ時に回収し、同時に10000件まで保持する。上限到達時は既存のカウンターを追い出して制限を回避させず、新規キーを拒否する。

## 本番セッション鍵（#29）

`APP_ENV=production` では `SESSION_SECRET` の明示設定が必要で、未設定・空・32文字未満・既知の開発用初期値を拒否する。Terraformは既存どおり乱数鍵をSSMから渡す。

既存配置で開発用初期値を使っていた場合は、新しいランダム鍵を用意して秘密情報ストアの値を更新し、APIを再配置する。旧鍵で署名されたセッションは検証できなくなるので、職員は再ログインする。今回の対応では本番の秘密情報の確認・交換・再配置は行っていない。

## 報告の保存と復旧（#21〜#23）

通常報告はオンライン時も、POSTを開始する前に端末へ保存する。待ち時間はレスポンス本文の読込を含め15秒に制限する。タイムアウトは未受理と断定できないため、同じ `client_event_id` の報告を保持して再送する。直接送信と自動再送が重なったときは同一IDの処理を共有する。

HTTPが2xxでもHTML、不正JSON、null、報告ID・避難所・人数・水在庫・緊急度・メモの不一致などは受理確認済みとしない。正しい受理結果を確認するまではキューから削除しない。ログアウト等、204を意図するAPIは引き続き使える。

IndexedDBを読めない場合は、全件を確認できていないことを表示し、件数を0と断定しない。次回の読取でDBを開き直し、localStorageの退避分を統合する。現場画面は障害中も再試行し、確認できた退避分は再送できる。DB障害とlocalStorage障害の両方で保存できなければ、入力を消さずエラーを返す。

## Packetの未来時刻と既存データ（#24）

v2の元の `reported_at`、`hub_received_at`、`raw_packet` は保持する。いずれかがAPIの受信時刻より10分を超えて未来なら `time_trust=UNTRUSTED` にし、Hub時刻かAPI受信時刻の早い方を観測時刻へ使う。小さな時計ずれでも観測時刻はAPI受信時刻を上限とする。過去のHub時刻による遅延配送は保持する。

Alembic `0006_packet_clock_correction` は、既存の未来向きのLoRa観測を保存時刻へ補正する。変更前の観測時刻・署名ログの時刻信頼状態を `packet_clock_corrections` へ退避し、downgradeで復元できる。補正後に別の値へ変更された行の観測時刻は、downgradeで上書きしない。適用とロールバックはPostgreSQL上の往復テストで確認する。

## ダッシュボードの鮮度（#25）

取得失敗時は保持データを表示し、失敗・保持データ利用・最終取得成功日時を示す。観測から24時間を超えた情報は1分ごとに再評価して鮮度警告を付け、APIと同じALERT/補助要請を表示する。明示された救助・医療・食料等の要請は補助判定で置き換えない。カードの更新時刻には日付も含める。
