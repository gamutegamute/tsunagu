// 状態(ステータス)ごとの日本語ラベル。CSSクラス名は英語のまま(status.toLowerCase())で管理する。
const STATUS_LABELS_JA = {
  NORMAL: "通常",
  WARNING: "注意",
  ALERT: "警戒",
  CRITICAL: "重大",
  UNKNOWN: "不明",
};

function toStatusClassName(status) {
  return status.toLowerCase();
}

function formatUpdatedAt(observedAtIsoString) {
  if (!observedAtIsoString) return "まだ報告がありません";
  const time = new Date(observedAtIsoString).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  return `最終更新 ${time}`;
}

/**
 * 避難所1件分の状況を表示するカード(Figmaの ShelterCard コンポーネントを再現)。
 * onClickを渡すと、決定事項16の詳細画面遷移のようにクリック可能なカードになる。
 */
export default function ShelterCard({ shelterStatus, onClick, onVerificationChange }) {
  const { shelter, latest_observation: observation, status, request_code: requestCode } = shelterStatus;
  const statusClassName = toStatusClassName(status);
  const isClickable = typeof onClick === "function";
  const verificationStatus = observation?.verification_status ?? "UNVERIFIED";

  return (
    <article
      className={`shelter-card ${statusClassName} ${isClickable ? "shelter-card-clickable" : ""}`}
      onClick={onClick}
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={
        isClickable
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") onClick(event);
            }
          : undefined
      }
    >
      <div className="shelter-card-accent" aria-hidden="true" />
      <div className="shelter-card-body">
        <div className="shelter-card-title-row">
          <h3>
            {shelter.id} {shelter.name}
          </h3>
          <span className={`status-badge ${statusClassName}`}>
            {status} {STATUS_LABELS_JA[status] ?? ""}
          </span>
        </div>

        <div className="shelter-card-stats">
          <div className="shelter-stat">
            <span className="shelter-stat-label">人数</span>
            <div className="shelter-stat-value">
              <strong>{observation?.people_count ?? "-"}</strong>
              <span>人</span>
            </div>
          </div>
          <div className="shelter-stat">
            <span className="shelter-stat-label">水在庫</span>
            <div className="shelter-stat-value">
              <strong>{observation?.water_stock ?? "-"}</strong>
              <span>L</span>
            </div>
          </div>
        </div>

        {observation && (
          <p className="reporter">
            {observation.source === "emergency_packet"
              ? "📡 報告者名・メモ: LoRa経由のため未取得"
              : `👤 報告者: ${observation.reporter_name || "不明"}`}
          </p>
        )}

        {observation && (
          <div className="verification-row" onClick={(event) => event.stopPropagation()}>
            <span className={`verification-badge ${verificationStatus.toLowerCase()}`}>
              {verificationStatus === "VERIFIED" ? "確認済み" : "未確認"}
            </span>
            {verificationStatus === "UNVERIFIED" && onVerificationChange && (
              <div className="verification-actions">
                <button type="button" onClick={() => onVerificationChange(observation.id, "VERIFIED")}>確認</button>
                <button type="button" className="reject-button" onClick={() => onVerificationChange(observation.id, "REJECTED")}>却下</button>
              </div>
            )}
          </div>
        )}

        <div className="shelter-card-footer">
          <span className="shelter-card-updated">{formatUpdatedAt(observation?.observed_at)}</span>
          {requestCode && <span className="request-code-chip">{requestCode}</span>}
        </div>
      </div>
    </article>
  );
}
