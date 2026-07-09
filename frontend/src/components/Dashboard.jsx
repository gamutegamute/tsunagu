import DashboardSummary from "./DashboardSummary.jsx";
import ShelterCard from "./ShelterCard.jsx";

/**
 * 本部ダッシュボード。
 * タブ切り替え・検索・絞り込み・並び替えはStep 2で追加する。今はまだ元のApp.jsxと
 * 同じ「集計タイル + 避難所カード一覧」のみ。
 */
export default function Dashboard({ shelterStatusList, onSyncButtonClick }) {
  return (
    <section className="panel dashboard-panel">
      <div className="section-title">
        <h2>本部ダッシュボード</h2>
        <button type="button" id="syncButton" onClick={onSyncButtonClick}>
          同期
        </button>
      </div>

      <DashboardSummary shelterStatusList={shelterStatusList} />

      <div className="shelter-grid">
        {shelterStatusList.map((shelterStatus) => (
          <ShelterCard key={shelterStatus.shelter.id} shelterStatus={shelterStatus} />
        ))}
      </div>
    </section>
  );
}
