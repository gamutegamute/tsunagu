import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, fetchDemoControlStatus, resetDemoData } from "../api.js";
import AuthStatus from "../components/AuthStatus.jsx";

function CountSummary({ counts }) {
  if (!counts) return null;
  return (
    <dl className="demo-counts">
      <div><dt>避難所</dt><dd>{counts.shelters}</dd></div>
      <div><dt>報告</dt><dd>{counts.observations}</dd></div>
      <div><dt>LoRa受信ログ</dt><dd>{counts.emergency_packets}</dd></div>
    </dl>
  );
}

export default function DemoControlPage() {
  const [status, setStatus] = useState(null);
  const [confirmation, setConfirmation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    fetchDemoControlStatus()
      .then(setStatus)
      .catch((error) => {
        setUnavailable(error instanceof ApiError && error.status === 404);
        if (!(error instanceof ApiError) || error.status !== 404) setMessage(error.message);
      })
      .finally(() => setLoading(false));
  }, []);

  const canReset = status
    && confirmation === status.confirmation_phrase
    && acknowledged
    && !submitting;

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canReset) return;
    if (!window.confirm("本番環境の現在データを削除し、デモ用データへ戻します。実行しますか？")) return;

    setSubmitting(true);
    setMessage("");
    try {
      const result = await resetDemoData(confirmation);
      setStatus((current) => ({ ...current, counts: result.counts }));
      setConfirmation("");
      setAcknowledged(false);
      setMessage("デモデータを初期化しました。ダッシュボードで表示を確認してください。");
    } catch (error) {
      setMessage(error.message || "デモデータの初期化に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div><h1>TSUNAGU</h1><p>デモ管理</p></div>
        <AuthStatus />
      </header>
      <main className="demo-control-page">
        <div className="demo-control-heading">
          <div><p className="eyebrow">管理者専用</p><h2>デモデータの初期化</h2></div>
          <Link className="outline-button" to="/dashboard">ダッシュボードへ戻る</Link>
        </div>

        {loading && <p>設定を確認しています。</p>}
        {unavailable && <p className="demo-control-unavailable">この操作は現在利用できません。</p>}
        {!loading && status && (
          <form className="demo-reset-form" onSubmit={handleSubmit}>
            <div className="demo-warning-band">
              <strong>現在の報告・インシデント・LoRa受信ログは削除されます</strong>
              <p>処理が完了すると、毎回同じ3避難所とデモ報告へ戻ります。端末内の未送信キューは対象外です。</p>
            </div>

            <section aria-labelledby="current-demo-data">
              <h3 id="current-demo-data">現在の登録件数</h3>
              <CountSummary counts={status.counts} />
            </section>

            <label className="form-label" htmlFor="demo-confirmation">
              確認のため「{status.confirmation_phrase}」と入力
            </label>
            <input
              id="demo-confirmation"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
            />
            <label className="demo-acknowledgement">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              現在の本番データが削除されることを確認しました
            </label>
            <button className="danger-button" type="submit" disabled={!canReset}>
              {submitting ? "初期化しています" : "デモデータを初期化"}
            </button>
          </form>
        )}
        {message && <p className="demo-control-message" role="status">{message}</p>}
      </main>
    </>
  );
}
