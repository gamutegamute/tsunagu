function summarizeShelterStatusList(shelterStatusList) {
  const initialTotals = { totalPeople: 0, totalWater: 0, warningCount: 0, alertOrUnknownCount: 0 };

  return shelterStatusList.reduce((totals, shelterStatus) => {
    const observation = shelterStatus.latest_observation;
    const statusName = shelterStatus.status.toLowerCase();
    const isWarning = statusName === "warning";
    const isAlertOrUnknown = statusName === "alert" || statusName === "unknown";

    return {
      totalPeople: totals.totalPeople + (observation?.people_count || 0),
      totalWater: totals.totalWater + (observation?.water_stock || 0),
      warningCount: totals.warningCount + (isWarning ? 1 : 0),
      alertOrUnknownCount: totals.alertOrUnknownCount + (isAlertOrUnknown ? 1 : 0),
    };
  }, initialTotals);
}

/** ダッシュボード上部に並ぶ、4つの集計タイル。 */
export default function DashboardSummary({ shelterStatusList }) {
  const totals = summarizeShelterStatusList(shelterStatusList);

  return (
    <div className="summary">
      <div className="metric">
        <strong>{totals.totalPeople}</strong>
        <span>合計人数</span>
      </div>
      <div className="metric">
        <strong>{totals.totalWater}</strong>
        <span>水在庫</span>
      </div>
      <div className="metric">
        <strong>{totals.warningCount}</strong>
        <span>注意</span>
      </div>
      <div className="metric">
        <strong>{totals.alertOrUnknownCount}</strong>
        <span>警戒/不明</span>
      </div>
    </div>
  );
}
