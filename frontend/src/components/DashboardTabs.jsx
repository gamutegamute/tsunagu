// Headquarters Dashboardの2つのタブ(決定事項15)。
const TABS = [
  { id: "status", label: "状況一覧" },
  { id: "incidents", label: "インシデント管理" },
];

/** タブの見た目と切り替えだけを担当するコンポーネント。中身の出し分けは親(Dashboard.jsx)が行う。 */
export default function DashboardTabs({ activeTabId, onChangeTab }) {
  return (
    <div className="dashboard-tab-bar">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`dashboard-tab ${activeTabId === tab.id ? "is-active" : ""}`}
          onClick={() => onChangeTab(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
