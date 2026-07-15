import IncidentUrgencyBadge from "./IncidentUrgencyBadge.jsx";

function formatObservedAt(observedAtIso, variant) {
  if (!observedAtIso) return "";
  const date = new Date(observedAtIso);
  const time = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  if (variant === "mobile") {
    return `発生 ${time}`;
  }
  const monthDay = date.toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" });
  return `${monthDay} ${time}`;
}

/**
 * Incident1件分のカード(Figmaの IncidentCard コンポーネントを再現)。
 * ボタン等の操作行はモバイル/PCで内容が異なるため actions として差し込む。
 */
export default function IncidentCard({ incident, variant = "mobile", assigneeLabel, statusNote, resolutionInfo, actions }) {
  return (
    <article className="incident-card">
      <div className="incident-card-title-row">
        <p className="incident-card-shelter-name">
          {incident.shelter.id} {incident.shelter.name}
        </p>
        <IncidentUrgencyBadge urgency={incident.urgency} />
      </div>
      <p className="incident-card-memo">{incident.memo}</p>
      <div className="incident-card-meta-row">
        <span className="incident-card-meta-time">{formatObservedAt(incident.observedAt, variant)}</span>
        {assigneeLabel && (
          <span className="assignee-tag">
            <span className="assignee-tag-dot" />
            {assigneeLabel}
          </span>
        )}
      </div>
      {statusNote && <p className="incident-card-status-note">{statusNote}</p>}
      {resolutionInfo && (
        <div className="incident-card-resolution-info">
          <p className="incident-card-resolution-memo">メモ: {resolutionInfo.memo}</p>
          <p className="incident-card-resolution-approval">
            ✓ 承認: {resolutionInfo.approverName}(本部)・
            {new Date(resolutionInfo.approvedAt).toLocaleString("ja-JP", {
              month: "2-digit",
              day: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            確定
          </p>
        </div>
      )}
      {actions && <div className="incident-card-action-row">{actions}</div>}
    </article>
  );
}
