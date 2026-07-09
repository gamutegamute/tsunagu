/**
 * 非常時(Emergency Mode)にLoRaで送る最低限のパケットを組み立てるロジック。
 * 本来はバックエンドが判定する内容(status/request_code)だが、非常時は通信不安定な
 * 前提のため、端末側だけで完結する簡易判定を行っている。
 * (元のApp.jsx内のロジックをそのまま移動しただけで、中身は変えていない)
 */
export function buildEmergencyPacket(report, status, requestCode) {
  const observedAt = new Date(report.observed_at);
  const time = observedAt.toTimeString().slice(0, 5);
  return `v1|${report.shelter_id}|${time}|${report.people_count}|${report.water_stock}|${status}|${requestCode || "REQ_CONFIRM"}`;
}

export function decideLocalStatus(report) {
  if (report.urgency === "CRITICAL") return "ALERT";
  if (report.urgency === "HIGH" || report.water_stock < 20) return "WARNING";
  return "NORMAL";
}

export function decideLocalRequestCode(report, status) {
  if (report.water_stock < 20) return "REQ_WATER";
  if (status === "ALERT") return "REQ_CONFIRM";
  return null;
}
