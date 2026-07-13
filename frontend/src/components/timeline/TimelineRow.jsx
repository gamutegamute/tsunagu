import IncidentUrgencyBadge from "../incident/IncidentUrgencyBadge.jsx";

function formatDateTime(iso) {
  const date = new Date(iso);
  const monthDay = date.toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" });
  const time = date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  return `${monthDay} ${time}`;
}

/** Timeline1件分の行(本部PC向け、全避難所横断の報告履歴)。 */
export default function TimelineRow({ observedAt, shelter, reporterName, urgency, summary, source }) {
  const isFromLora = source === "emergency_packet";

  return (
    <div className="timeline-row">
      <span className="timeline-row-time">{formatDateTime(observedAt)}</span>
      <span className="timeline-row-shelter">
        {shelter.id} {shelter.name}
      </span>
      <span className="timeline-row-reporter">
        {isFromLora ? "📡 LoRa経由" : `👤 ${reporterName || "不明"}`}
      </span>
      <IncidentUrgencyBadge urgency={urgency} />
      <p className="timeline-row-summary">{isFromLora ? "(メモはLoRa経由のため未取得)" : summary || "(メモなし)"}</p>
    </div>
  );
}
