import { useEffect } from "react";
import { useNavigate } from "react-router";
import TimelineShelterGroup from "../components/timeline/TimelineShelterGroup.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useDashboardData } from "../hooks/useDashboardData.js";
import { mergeEmergencyDataIntoDashboard } from "../utils/emergencyPacket.js";

/**
 * PC向けTimeline画面(/dashboard/timeline)。
 * 全避難所の報告履歴を時系列(新しい順)で表示する(決定事項22: PC専用、モバイルは送信履歴のみ)。
 *
 * 避難所ごとに最新の報告を1行表示し、「▼ 過去の報告を見る」で
 * GET /api/shelters/{id}/observations を呼んで過去の報告を遡って確認できる
 * (アコーディオン形式、決定事項34-a関連の履歴API追加に対応)。
 */
export default function TimelinePage() {
  const navigate = useNavigate();
  const shelters = useShelterList();
  const { dashboardItems, emergencyPackets, reloadDashboard } = useDashboardData();

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const shelterStatusList = mergeEmergencyDataIntoDashboard(dashboardItems, emergencyPackets, shelters);
  const timelineEntries = shelterStatusList
    .filter((item) => item.latest_observation)
    .map((item) => ({ shelter: item.shelter, observation: item.latest_observation }))
    .sort((a, b) => new Date(b.observation.observed_at) - new Date(a.observation.observed_at));

  return (
    <>
      <header className="topbar">
        <div className="shelter-detail-title-group">
          <button type="button" className="icon-nav-button timeline-back-link" onClick={() => navigate("/dashboard")}>
            <span aria-hidden="true">←</span>
            <span>状況一覧</span>
          </button>
          <h1 className="shelter-detail-title">Timeline — 全避難所 報告履歴</h1>
        </div>
      </header>

      <main className="layout-desktop">
        <section className="panel">
          <p className="incident-header-note-dark timeline-note">
            全避難所の最新の報告を新しい順に表示しています。避難所ごとに「▼ 過去の報告を見る」を押すと、過去の報告履歴を遡って確認できます。
          </p>

          <div className="timeline-list">
            {timelineEntries.length === 0 && <p className="incident-empty-state">報告履歴はまだありません</p>}
            {timelineEntries.map(({ shelter, observation }) => (
              <TimelineShelterGroup key={shelter.id} shelter={shelter} latestObservation={observation} />
            ))}
          </div>
        </section>
      </main>
    </>
  );
}
