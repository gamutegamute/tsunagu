# ShelterOS v0.8

Offline First Disaster Observability Platform

> 通信が途絶えても、現場の状況は途絶えない。

## 1. What Is ShelterOS?

ShelterOS は、災害時の避難所・現場状況を記録、標準化、共有、観測するための Offline First 型プラットフォームです。

ShelterOS は、単なる避難所管理アプリや物資管理アプリではありません。災害時の意思決定を支えるために、現場情報を止めずに集める「現場情報インフラ」を目指します。

## 2. Problem

災害時には、通信障害、停電、道路寸断、人員不足が同時に発生します。

その結果、本部は以下を把握できなくなります。

- 今どの避難所に何人いるのか
- 水や物資がどれくらい残っているのか
- どの避難所が優先支援を必要としているのか
- 最後にいつ報告があったのか

現在も多くの現場では、紙、電話、FAX、Excel による報告が中心であり、情報共有の遅れが意思決定の遅れにつながります。

ShelterOS が解決したい本質的な課題は「情報不足」です。

## 3. Concept

ShelterOS は、SRE やシステム運用で使われる Observability の考え方を災害対応に応用します。

通常の Observability はシステムを観測しますが、ShelterOS では避難所や現場を観測対象にします。

## 4. Three Pillars

### Monitoring

避難所の状態を継続的に観測します。

- 人数
- 水在庫
- 更新時刻
- 緊急度
- 自由メモ

### Alerting

異常状態を自動で検知します。

- 水が20以下
- 人数が急増
- 24時間以上更新なし
- 緊急度が RED / CRITICAL

### Forecasting

今後の不足を簡易的に予測します。

例:

```text
現在の水: 50
過去24時間の消費: 20
予測: 約2日で水不足
```

## 5. Core Value: Offline First

ShelterOS の最大の特徴は LoRa ではなく、Offline First です。

通信できない状態でも以下を可能にします。

- 入力
- 保存
- 閲覧
- 後から同期

通信復旧後、ローカルに保存された報告をサーバーへ自動同期します。

## 6. Communication Modes

### Normal Mode

通常通信が可能な状態です。

- Wi-Fi
- LTE
- Starlink

動作:

- フル同期
- ダッシュボード即時反映
- 履歴保存

### Offline Mode

完全に通信が切れている状態です。

動作:

- ブラウザ内にローカル保存
- 未同期レポートとして保持
- 画面閲覧は継続可能

### Emergency Mode

通常通信が使えない場合の最後の通信手段です。

利用技術:

- LoRa

動作:

- 最小限の Emergency Packet を送信
- 本部側で最低限の状況を把握

## 7. LoRa Positioning

LoRa は ShelterOS の主役ではありません。

ShelterOS の価値は、通信断でも情報を失わない Offline First 設計にあります。

LoRa は、その価値を補強するための「最後の通信手段」として扱います。

v0.8 では街中の LoRaWAN ゲートウェイは前提にしません。避難所ノードと本部ノードを自分たちで持ち込む、閉じた P2P 通信として扱います。

## 8. Emergency Packet

LoRa で送る最小限の情報です。

- 避難所ID
- 時刻
- 人数
- 水
- 状態
- 要請コード

例:

```text
AIT001|21:04|170|18|WARNING|REQ_WATER
```

## 9. MVP Scope

THE HACK では、「現場の状況を正確に報告できること」を最重要とします。

素早さは重要ですが、最優先ではありません。災害時に本当に困るのは、報告が遅いことだけではなく、誤った人数・水在庫・緊急度が本部に伝わることです。

そのため MVP では、入力項目を絞りつつ、確認しやすく、入力ミスが起きにくい報告体験を目指します。

入力項目は最小限にします。

- 人数
- 水
- 緊急度
- 自由メモ

対象は、まず大学内での小規模検証です。

- 愛知工業大学
- 部室
- 研究室
- 学内の小さな実験スペース
- 数人から十数人規模の模擬運用

## 10. Main Screens

### Field Report

現場担当者が報告する画面です。

- 避難所選択
- 人数入力
- 水在庫入力
- 緊急度選択
- メモ入力
- 報告送信
- オフライン時はローカル保存

現場画面では、専門用語を出しません。

```text
人数
水
緊急度
メモ
報告する
未送信 1件
```

### Headquarters Dashboard

本部が状況を見るメイン画面です。

- 各避難所の状態
- 人数
- 水在庫
- 最終更新時刻
- 警告状態
- 要請コード
- 簡易Forecast

### Offline / Emergency Mode

通信状態を確認する画面です。

- Normal / Offline / Emergency の状態
- 未同期レポート数
- LoRa Emergency Packet
- 送信結果

### Timeline

報告履歴を時系列で表示します。

- 誰が
- いつ
- どの避難所について
- 何を報告したか

### Incident

アラート発生後の対応管理です。

- 未確認
- 確認済み
- 対応済み

### Forecast

水や人数の推移から不足予測を表示します。最初は簡易計算で実装します。

## 11. Demo Scenario

THE HACK 向けの5分デモ想定です。

1. 避難所Aで通常報告する
   - 人数150
   - 水50
2. 本部ダッシュボードへ即時反映される
3. Wi-Fiを切断する
4. 避難所Aで新しい報告を入力する
   - 人数170
   - 水18
5. Offline Mode としてローカル保存される
6. LoRa で Emergency Packet を送信する
7. 本部側で WARNING が表示される
8. Wi-Fiを復旧する
9. 未同期レポートが自動同期される
10. Timeline に履歴が追加される
11. Forecast に「約2日で水不足」と表示される

## 12. Demo Risk Strategy

LoRa は本番デモの必須成功条件にしません。

メイン成功条件:

- PWAで入力できる
- ローカル保存できる
- 復旧後に同期できる
- ダッシュボードに反映できる

追加演出:

- LoRa Emergency Packet

LoRa が会場環境で失敗しても、ShelterOS の中核価値は Offline First として説明できる構成にします。

本番対策:

- LoRa実機デモ
- LoRa受信済みログの再生ボタン
- Emergency Packet を手動注入するバックアップ

## 13. Concerns And Responses

### Concern: 既存の避難所管理アプリと被る

Response:

ShelterOS は避難所管理アプリではなく、通信断を前提にした「現場報告・状況観測レイヤー」です。

既存の避難所管理や物資管理の前段で、現場データを止めずに集めるための仕組みとして位置付けます。

### Concern: 防災はハッカソンの定番テーマで既視感がある

Response:

防災アプリではなく、以下に絞って差別化します。

- Offline First
- Observability
- LoRa fallback
- 正確で迷わない現場報告
- 大学内の小規模検証から始める

### Concern: LoRa が本番で失敗する可能性がある

Response:

LoRa は「最後の通信手段」として扱い、プロダクトの主役にしません。

本番デモの主役は Offline First です。

### Concern: PWA / Service Worker が不安定

Response:

最初の実装は Service Worker に依存しすぎません。

- オフライン保存: localStorage / IndexedDB
- 未同期キュー: localStorage / IndexedDB
- 通信断判定: アプリ内の Demo Offline ボタン
- Service Worker: あれば加点、なくても成立

### Concern: 現場の人が横文字UIを使えない

Response:

現場画面では専門用語を出しません。

Observability / Alerting / Forecasting は本部側・審査員向けの設計思想として扱い、現場担当者は人数・水・緊急度・メモだけを迷わず正確に入力します。

### Concern: LoRa のインフラは誰が設置するのか

Response:

v0.8 では街中の LoRaWAN インフラを前提にしません。

自分たちが持ち込む T-Beam 2台で、避難所ノードと本部ノードの P2P 通信として実証します。

## 14. Technical Stack

### Frontend

- PWA
- React 想定
- オフライン対応
- localStorage / IndexedDB による一時保存

### Backend

- FastAPI

### Database

- PostgreSQL

### Infra

- Docker
- AWS ECS
- RDS
- CloudWatch

### CI/CD

- GitHub Actions

### IaC

- Terraform

### Future Observability

- OpenTelemetry
- Prometheus
- Grafana
- Datadog

## 15. Current Implementation

This repository currently contains a compact MVP:

- FastAPI backend
- PostgreSQL schema
- Static PWA frontend
- Offline local save and later sync using `client_event_id`
- Alert/status rules for people count, water stock, and stale reports
- Emergency packet view for LoRa-style minimum reports

## 16. Alert Rules

- `UNKNOWN`: no observation exists.
- `ALERT`: the latest observation is older than 24 hours.
- `WARNING`: water stock is lower than 20.
- `WARNING`: urgency is `HIGH`.
- `ALERT`: urgency is `CRITICAL`.
- `NORMAL`: none of the above apply.

## 17. Hardware Plan

THE HACK の最小構成:

- LILYGO T-Beam x2
- microUSB cable x2
- PC x1

あると良いもの:

- Mobile battery x1 or x2

後回しでよいもの:

- 18650 battery
- Antenna extension cable
- High-gain antenna
- Case

注意:

- 付属アンテナは必ず接続して送信する。
- 18650電池は扱いに注意が必要なので、最初はUSB給電またはモバイルバッテリー給電を優先する。
- 大学内の検証や屋外利用では、技適取得済みのボードを使う。

## 18. Team Roles

### Frontend

- Field Report UI
- Dashboard UI
- Offline状態表示
- Timeline / Forecast 表示

### Backend

- FastAPI
- CRUD API
- PostgreSQL設計
- 同期処理
- Alert判定

### Infra

- Docker
- AWS ECS
- RDS
- CI/CD
- 将来的なLoRa接続設計

### LoRa / Demo

- T-Beam の送受信
- Emergency Packet設計
- PCへのSerial連携
- デモシナリオ整理
- 本番失敗時のバックアップ導線

## 19. Quick Start

```powershell
docker compose up --build
```

Then open:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/docs
```

## 20. Local Development Without Docker

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:DATABASE_URL="postgresql://shelteros:shelteros@localhost:5432/shelteros"
.\.venv\Scripts\uvicorn app.main:app --reload
```

Run tests:

```powershell
cd backend
python -m pytest
```

## 21. Winning Narrative

ShelterOS の勝ち筋は「LoRaで防災DXします」ではありません。

勝ち筋は以下です。

```text
通信が途絶えても
現場は報告できる
本部は観測できる
復旧後に同期できる
最後の手段としてLoRaで最低限の情報を届けられる
```

ShelterOS は、避難所管理アプリではなく、通信断を前提にした災害時の現場情報プラットフォームです。
