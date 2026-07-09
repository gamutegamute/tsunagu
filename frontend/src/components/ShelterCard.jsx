function toStatusClassName(status) {
  return status.toLowerCase();
}

/** 避難所1件分の状況を表示するカード。 */
export default function ShelterCard({ shelterStatus }) {
  const { shelter, latest_observation: observation, status, request_code: requestCode } = shelterStatus;
  const statusClassName = toStatusClassName(status);

  return (
    <article className={`shelter-card ${statusClassName}`}>
      <div className="card-title">
        <h3>
          {shelter.id} {shelter.name}
        </h3>
        <span className={`badge ${statusClassName}`}>{status}</span>
      </div>
      <div className="facts">
        <div className="fact">
          <strong>{observation?.people_count ?? "-"}</strong>
          <span>人数</span>
        </div>
        <div className="fact">
          <strong>{observation?.water_stock ?? "-"}</strong>
          <span>水</span>
        </div>
      </div>
      {observation && (
        <p className="reporter">
          {observation.source === "emergency_packet" ? "📡 LoRaパケット" : `👤 報告者: ${observation.reporter_name || "不明"}`}
        </p>
      )}
      <p className="memo">{observation?.memo || requestCode || "要請なし"}</p>
      <p className="timestamp">{observation ? new Date(observation.observed_at).toLocaleString() : "報告なし"}</p>
    </article>
  );
}
