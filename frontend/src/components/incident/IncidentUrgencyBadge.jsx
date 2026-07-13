const STATUS_LABELS_JA = {
  NORMAL: "通常",
  WARNING: "注意",
  ALERT: "警戒",
  CRITICAL: "重大",
  UNKNOWN: "不明",
};

/** 避難所カード(ShelterCard)と同じ .status-badge スタイルを使う緊急度バッジ。 */
export default function IncidentUrgencyBadge({ urgency }) {
  const className = `status-badge ${(urgency || "unknown").toLowerCase()}`;
  return (
    <span className={className}>
      {urgency} {STATUS_LABELS_JA[urgency] ?? ""}
    </span>
  );
}
