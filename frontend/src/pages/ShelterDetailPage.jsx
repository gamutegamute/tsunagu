import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ShelterCard from "../components/ShelterCard.jsx";
import WaterTrendChart from "../components/shelter-detail/WaterTrendChart.jsx";
import PeopleTrendChart from "../components/shelter-detail/PeopleTrendChart.jsx";
import PcIncidentCard from "../components/incident/PcIncidentCard.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useDashboardData } from "../hooks/useDashboardData.js";
import { useIncidents } from "../hooks/useIncidents.js";
import { mergeEmergencyDataIntoDashboard } from "../utils/emergencyPacket.js";
import { getHistory } from "../utils/shelterObservationHistory.js";
import { getCapacity } from "../utils/shelterCapacity.js";

/**
 * PC向け避難所詳細画面(/dashboard/shelters/:shelterId、決定事項16)。
 * ShelterCardクリック時の遷移先。その避難所のインシデント一覧と推移・予測を表示する。
 */
export default function ShelterDetailPage() {
  const { shelterId } = useParams();
  const navigate = useNavigate();
  const shelters = useShelterList();
  const { dashboardItems, reloadDashboard } = useDashboardData();
  const { incidents, refresh: refreshIncidents, refreshLocalState } = useIncidents();

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const shelterStatusList = mergeEmergencyDataIntoDashboard(dashboardItems, [], shelters);
  const shelterStatus = shelterStatusList.find((item) => item.shelter.id === shelterId);
  const shelterIncidents = incidents.filter((incident) => incident.shelter.id === shelterId);
  const history = getHistory(shelterId);
  const capacity = getCapacity(shelterId);

  if (!shelterStatus) {
    return (
      <main className="layout-desktop">
        <p>避難所 {shelterId} が見つかりません。</p>
        <button type="button" className="secondary-button" onClick={() => navigate("/dashboard")}>
          状況一覧に戻る
        </button>
      </main>
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="shelter-detail-title-group">
          <button type="button" className="text-link-button shelter-detail-back-link" onClick={() => navigate("/dashboard")}>
            ← 状況一覧
          </button>
          <h1 className="shelter-detail-title">
            {shelterStatus.shelter.id} {shelterStatus.shelter.name} — 詳細
          </h1>
        </div>
      </header>

      <main className="layout-desktop">
        <div className="shelter-detail-summary">
          <ShelterCard shelterStatus={shelterStatus} />
        </div>

        <section className="shelter-detail-section">
          <div className="section-header-row">
            <h3>この避難所のインシデント</h3>
            <p className="incident-header-note incident-header-note-dark">確認済みにする・承認は本部(PC)のみ操作可能</p>
          </div>
          <div className="shelter-detail-incident-grid">
            {shelterIncidents.length === 0 && <p className="incident-empty-state">この避難所のインシデントはありません</p>}
            {shelterIncidents.map((incident) => (
              <PcIncidentCard
                key={incident.id}
                incident={incident}
                onChanged={() => {
                  refreshLocalState();
                  refreshIncidents();
                }}
              />
            ))}
          </div>
        </section>

        <section className="shelter-detail-section">
          <div className="section-header-row">
            <h3>推移・予測</h3>
            <p className="incident-header-note incident-header-note-dark">水は「約◯日で不足」を予測・人数は推移表示のみ</p>
          </div>
          <div className="shelter-detail-charts">
            <WaterTrendChart history={history} />
            <PeopleTrendChart history={history} capacity={capacity} />
          </div>
        </section>
      </main>
    </>
  );
}
