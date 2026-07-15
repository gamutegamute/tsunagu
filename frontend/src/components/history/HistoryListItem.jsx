import IncidentUrgencyBadge from "../incident/IncidentUrgencyBadge.jsx";

/** 送信履歴1件分の行(Figmaの HistoryItem コンポーネントを再現)。 */
export default function HistoryListItem({ time, shelterLabel, urgency }) {
  return (
    <div className="history-item">
      <span className="history-item-time">{time}</span>
      <span className="history-item-shelter">{shelterLabel}</span>
      <IncidentUrgencyBadge urgency={urgency} />
    </div>
  );
}
