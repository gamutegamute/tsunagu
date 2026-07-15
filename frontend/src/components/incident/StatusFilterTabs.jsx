/**
 * Incident一覧の状態別タブ(モバイル: 未確認/対応済み、PC: 未確認/確認済み/対応済み)。
 * 見た目はFigmaのStatusTabコンポーネントを再現(選択中は濃色の塗り、非選択は白背景)。
 */
export default function StatusFilterTabs({ tabs, activeTabId, onChangeTab }) {
  return (
    <div className="incident-status-tab-row">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`incident-status-tab ${activeTabId === tab.id ? "is-active" : ""}`}
          onClick={() => onChangeTab(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
