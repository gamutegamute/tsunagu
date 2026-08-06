import IncidentUrgencyBadge from "../incident/IncidentUrgencyBadge.jsx";
import HistorySyncBadge from "./HistorySyncBadge.jsx";

/**
 * 送信履歴1件分のカード(決定事項33-a: 他画面(ShelterCard・IncidentCard)と
 * 統一感のあるデザインに改善)。
 *
 * 時計アイコンだけでは意味が伝わりにくい・見た目が良くないという指摘を受け、
 * 同期状態は専用のアイコン付きバッジ(HistorySyncBadge)で表す。statusは
 * 呼び出し元(HistoryPage、決定事項33追加対応: pendingReportsとの連携)が
 * 送信済み("sent")か未同期("unsynced")かを判定してそのまま渡す。
 */
export default function HistoryListItem({ time, shelterLabel, urgency, status = "sent" }) {
  const statusClassName = (urgency || "unknown").toLowerCase();

  return (
    <article className={`history-item ${statusClassName}`}>
      <div className="history-item-accent" aria-hidden="true" />
      <div className="history-item-body">
        <div className="history-item-title-row">
          <span className="history-item-shelter">{shelterLabel}</span>
          <IncidentUrgencyBadge urgency={urgency} />
        </div>
        <div className="history-item-meta-row">
          <span className="history-item-time">{time}</span>
          <HistorySyncBadge status={status} />
        </div>
      </div>
    </article>
  );
}
