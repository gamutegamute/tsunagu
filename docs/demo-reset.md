# デモデータのリセット

デモ当日など、DBを一度空にしてから決まったデモ用データだけを入れ直したいときの手順です。

## 実行方法

```powershell
docker compose exec api python -m app.reset_demo_data
```

これ1コマンドで、以下が順番に実行されます。

1. `shelters` / `observations` / `emergency_packets` を `TRUNCATE ... CASCADE` で空にする
2. `seed_demo_data()` を呼び出し、固定のデモデータ(避難所3件・報告2件・Emergency Packet 1件)を再投入する

成功すると次のように表示されます。

```text
デモデータをリセットしました(shelters/observations/emergency_packetsを初期化し、デモデータを再投入)。
```

## 安全ガード

誤って本番DBを空にする事故を防ぐため、以下の場合は何もせずエラーで終了します(終了コード1)。

- `APP_ENV=production` のとき
  ```text
  拒否: APP_ENV=production ではデモデータのリセットを実行できません。
  ```
- `DEMO_SEED=true` が設定されていないとき(リセット後にデモデータが再投入されず、テーブルが空のまま残ってしまうため)
  ```text
  拒否: DEMO_SEED=true が設定されていないため、リセット後にデモデータが再投入されません。実行前に環境変数 DEMO_SEED=true を設定してください。
  ```

ローカルの `docker-compose.yml` では `DEMO_SEED=true` が既定で設定されているため、通常は追加設定なしでそのまま実行できます。本番(Terraform)側は `DEMO_SEED=false` かつ `APP_ENV=production` のため、このスクリプトは本番環境では実行できません。

## 注意

- この操作は選択的な削除ではなく、3テーブルを丸ごと空にしてから再投入します。手動で追加した避難所やテスト報告も含めて全て消えます。
- 元に戻せません。デモ本番中の実行は避け、事前準備やリハーサル後のリセット用として使ってください。
