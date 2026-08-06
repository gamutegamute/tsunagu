import { useMemo, useState } from "react";
import StatusFilterTabs from "./incident/StatusFilterTabs.jsx";
import PcIncidentCard from "./incident/PcIncidentCard.jsx";
import { deriveIncidentsFromDashboard, isResolved } from "../utils/incidents.js";

const TABS = [
  { id: "unconfirmed", label: "未確認" },
  { id: "all", label: "一覧" },
  { id: "confirmed", label: "確認済み" },
  { id: "resolved", label: "対応済み" },
];

/**
 * Headquarters Dashboardの「インシデント管理」タブの中身(決定事項15)。
 * 全避難所のインシデントを横断的に一覧表示し、確認・対応済み・承認の操作を行う。
 *
 * 決定事項33-e: 未確認/確認済み/対応済みの3タブに加え、状態を問わず全件表示する
 * 「一覧」タブを追加した4タブ構成(未確認→一覧→確認済み→対応済み)。
 */
export default function IncidentManagementTab({ shelterStatusList }) {
  const [activeTabId, setActiveTabId] = useState("unconfirmed");
  const [refreshTick, setRefreshTick] = useState(0);

  const incidents = useMemo(
    () => deriveIncidentsFromDashboard(shelterStatusList),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shelterStatusList, refreshTick],
  );

  const visibleIncidents = incidents.filter((incident) => {
    if (activeTabId === "all") return true;
    if (activeTabId === "resolved") return isResolved(incident);
    if (activeTabId === "confirmed") return !isResolved(incident) && incident.confirmStatus === "CONFIRMED";
    return !isResolved(incident) && incident.confirmStatus !== "CONFIRMED";
  });

  function handleChanged() {
    setRefreshTick((tick) => tick + 1);
  }

  return (
    <div className="incident-management-tab">
      <div className="section-header-row">
        <h3>インシデント管理(全避難所)</h3>
        <p className="incident-header-note-dark">閲覧は全エリア可・対応確定は担当エリアのみ(承認制)</p>
      </div>

      <StatusFilterTabs tabs={TABS} activeTabId={activeTabId} onChangeTab={setActiveTabId} />

      <div className="shelter-detail-incident-grid">
        {visibleIncidents.length === 0 && <p className="incident-empty-state">該当するインシデントはありません</p>}
        {visibleIncidents.map((incident) => (
          <PcIncidentCard key={incident.id} incident={incident} onChanged={handleChanged} />
        ))}
      </div>
    </div>
  );
}
