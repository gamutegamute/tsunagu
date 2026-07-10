const BANNER_CONTENT_BY_MODE = {
  offline: {
    title: "オフライン — 通信復旧を待っています",
    description: "報告は端末に保存され、回線復帰後に自動で同期されます。",
  },
  emergency: {
    title: "非常時 — LoRa非常用通信で稼働中",
    description: "詳細データは端末に保存し、最低限の情報だけ送信します。",
  },
};

/** オフライン・非常時のときだけ表示する、状況説明バナー。通常時は何も表示しない。 */
export default function StatusHeroBanner({ networkMode }) {
  const content = BANNER_CONTENT_BY_MODE[networkMode];
  if (!content) return null;

  return (
    <div className={`status-hero ${networkMode}`}>
      <strong>{content.title}</strong>
      <span>{content.description}</span>
    </div>
  );
}
