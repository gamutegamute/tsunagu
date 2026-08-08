/**
 * 送信済み履歴(sentReportHistory、camelCase)と、まだ送信できていない
 * 保留キュー(pendingReports、APIペイロードそのままのsnake_case)を、
 * フィールド名を正規化した上で1つの一覧にマージし、時刻の新しい順に並べる。
 *
 * 状態は排他的(送信に成功した瞬間にpendingReportsから消えてsentReportHistoryに
 * 現れる設計)なので、同じ報告が両方に重複して現れることは想定していない。
 */
export function mergeHistoryEntries(sentHistory, pendingReports) {
  const sentEntries = sentHistory.map((entry, index) => ({
    key: `sent-${entry.sentAt ?? index}-${index}`,
    shelterId: entry.shelterId,
    urgency: entry.urgency,
    observedAt: entry.observedAt,
    status: "sent",
  }));

  const unsyncedEntries = pendingReports.map((report, index) => ({
    key: `unsynced-${report.client_event_id ?? index}`,
    shelterId: report.shelter_id ?? report.shelter_code,
    urgency: report.urgency,
    observedAt: report.observed_at,
    status: "unsynced",
  }));

  return [...sentEntries, ...unsyncedEntries].sort((a, b) => new Date(b.observedAt) - new Date(a.observedAt));
}
