# ShelterOS 認証・AWS本番構築手順

## 確定した認証方針

- 本部画面はGoogle認証を必須にする。
- Googleアカウントは許可リストに登録したメールアドレスだけ利用できる。
- 認証ユーザーを `hq` と `field` に分ける。
- 未ログインでも現場報告を送信できる。
- 匿名報告は1接続元あたり1分30件までに制限する。
- 匿名報告は `ANONYMOUS / UNVERIFIED` として保存する。
- 認証済み現場職員の報告は `AUTHENTICATED_FIELD / UNVERIFIED` として保存する。
- 本部職員だけが報告を `VERIFIED` または `REJECTED` に変更できる。
- LoRaゲートウェイはGoogle認証ではなく固定APIキーを使う。

許可メールアドレスはリポジトリへ記録せず、GitHub Environment `production` の暗号化Secretとして管理する。

## ローカル確認

```powershell
docker compose up --build -d
```

`http://localhost:8000/login`では、ローカル専用の本部・現場ログインを選択できる。本番環境で`AUTH_MODE=dev`を指定するとアプリは起動を拒否する。

ローカルLoRaゲートウェイには次の環境変数を設定する。

```powershell
$env:SHELTEROS_GATEWAY_API_KEY="local-gateway-key"
python .\tools\lora_serial_gateway.py --port COM6 --baud 115200
```

送信失敗Packetは`.shelteros/lora_gateway_queue.db`へ保存され、API復旧後に再送される。

## Google Cloudの準備

1. Google Cloud ConsoleでOAuth同意画面を作成する。
2. OAuthクライアントをWebアプリケーションとして作成する。
3. 承認済みリダイレクトURIへ次を登録する。

```text
https://<Cognitoドメイン接頭辞>.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
```

4. Client IDとClient SecretをGitHub EnvironmentのSecretへ登録する。

アプリはCognitoのAuthorization Code + PKCEを使用する。GoogleのトークンをブラウザのlocalStorageへ保存せず、FastAPIが署名付きHttpOnly Cookieを発行する。

## GitHub Environment設定

Repository Settingsから`production` Environmentを作り、可能ならRequired reviewersを設定する。

Secrets:

| 名前 | 内容 |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | GitHub OIDCから引き受けるAWS IAM Role |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret |
| `HQ_EMAILS_JSON` | `hq`許可メールのJSON配列 |
| `FIELD_EMAILS_JSON` | `field`許可メールのJSON配列 |

Variables:

| 名前 | 内容 |
|---|---|
| `TF_STATE_BUCKET` | Terraform state用S3バケット名 |
| `COGNITO_DOMAIN_PREFIX` | 世界で一意なCognitoドメイン接頭辞 |

メールアドレスは小文字へ正規化して照合される。

## Terraform stateの初期化

最初の一度だけ、管理者PCから実行する。

```powershell
cd infra/bootstrap-state
terraform init
terraform apply -var="state_bucket_name=<一意なS3バケット名>"
```

このTerraformはstate用S3バケットに加え、GitHub Actions用OIDC ProviderとデプロイRoleを作成する。すでにGitHub OIDC ProviderがあるAWSアカウントでは、次のように既存ARNを指定する。

```powershell
terraform apply `
  -var="state_bucket_name=<一意なS3バケット名>" `
  -var="github_oidc_provider_arn=<既存Provider ARN>"
```

出力された値を次のように登録する。

- `state_bucket_name`をGitHub Variable `TF_STATE_BUCKET`へ登録する。
- `github_deploy_role_arn`をGitHub Secret `AWS_DEPLOY_ROLE_ARN`へ登録する。

デプロイRoleの信頼先は、このリポジトリの`production` Environmentだけに限定される。初回構築を単純にするためAWS管理ポリシー`AdministratorAccess`を使用するので、GitHub EnvironmentにはRequired reviewersを必ず設定し、発表後はRoleを削除するか権限を縮小する。stateにはDBパスワードなどが含まれるため、公開・添付・コミットしない。

## 初回デプロイ

GitHub Actionsの「本番環境へ手動デプロイ」を開き、`first_deploy`を有効にして実行する。

1. ECR、RDS、Cognito、IAM、SSM Parameter Storeを作成する。
2. DockerイメージをECRへpushする。
3. ECS Express Modeを外部アクセス拒否の`setup`モードで作成する。
4. AWS発行のHTTPS URLをCognitoのCallback URLへ追加する。
5. `cognito`モードで再デプロイする。

通常の更新では`first_deploy`を無効にする。`main`へのマージだけでは本番更新されず、Environment承認後の手動実行でのみ更新される。

## LoRaゲートウェイを本番へ接続

APIキーをAWSから安全に取得し、ノートPCの環境変数へ設定する。画面共有やログへ値を表示しない。

```powershell
$env:SHELTEROS_API_URL="https://<AWS発行URL>/api/emergency-packets"
$env:SHELTEROS_GATEWAY_API_KEY="<SSMから取得した値>"
python .\tools\lora_serial_gateway.py --port COM6 --baud 115200
```

確認項目:

- APIキーなし・不一致はHTTP 401になる。
- API停止中のPacketはSQLiteに残る。
- API復旧後に同じPacketが一度だけ反映される。
- COMポートを抜いてもプロセスが終了せず、再接続後に受信を再開する。

## 本番前チェック

- `terraform validate`が成功する。
- Backend、Frontend、LoRa gatewayのCIが成功する。
- Google許可リスト外のアカウントが拒否される。
- `field`が避難所追加や報告確認を実行するとHTTP 403になる。
- 未ログインのField Reportは送信でき、未確認表示になる。
- オフライン中の報告が消えず、復旧後に同期される。
- `/health`はアプリ生存、`/ready`はDB接続を確認できる。
- CloudWatch LogsとRDS 7日バックアップを確認する。
