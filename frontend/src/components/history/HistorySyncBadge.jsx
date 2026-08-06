const LABELS = {
  sent: "送信済み",
  unsynced: "未同期",
};

function SentIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4.8 8.2L6.9 10.3L11.2 5.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function UnsyncedIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 11.2V4.8M5.6 7.2L8 4.8L10.4 7.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS = {
  sent: SentIcon,
  unsynced: UnsyncedIcon,
};

/**
 * 送信履歴の同期状態バッジ。
 *
 * 時計アイコン単体では「何を意味するか分からない」という指摘を受け、状態ごとに
 * 意味の異なるアイコン(送信済み=チェック、未同期=上矢印)+テキストラベルを
 * 必ず組み合わせて表示する(アイコンだけに頼らない)。両状態とも同じ「円+記号」の
 * トーンで揃え、見た目の統一感を持たせている。
 *
 * unsynced状態は、HistoryPageが保留キュー(pendingReports)由来のエントリに
 * 付与するstatusから渡ってくる(utils/historyEntries.jsを参照)。
 */
export default function HistorySyncBadge({ status }) {
  const Icon = ICONS[status];
  return (
    <span className={`history-sync-chip ${status}`}>
      <Icon />
      {LABELS[status]}
    </span>
  );
}
