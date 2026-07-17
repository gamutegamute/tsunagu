import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import TimelineRow from "../components/timeline/TimelineRow.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useDashboardData } from "../hooks/useDashboardData.js";
import { mergeEmergencyDataIntoDashboard } from "../utils/emergencyPacket.js";

/**
 * PC向けTimeline画面(/dashboard/timeline)。
 * 全避難所の報告履歴を時系列(新しい順)で表示する(決定事項22: PC専用、モバイルは送信履歴のみ)。
 *
 * 現状のバックエンドAPI(GET /api/dashboard・GET /api/observations/latest)は
 * 「避難所ごとの最新1件」しか返さないため、このTimelineも各避難所の最新報告
 * 1件ずつの一覧になる(過去の報告は含まれない)。詳細は申し送り事項を参照。
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
          <button type="button" className="text-link-button shelter-detail-back-link" onClick={() => navigate("/dashboard")}>
            ← 状況一覧
          </button>
          <h1 className="shelter-detail-title">Timeline — 全避難所 報告履歴</h1>
        </div>
      </header>

      <main className="layout-desktop">
        <section className="panel">
          <p className="incident-header-note-dark timeline-note">
            全避難所の最新の報告を新しい順に表示しています(各避難所の最新1件のみ。過去の報告履歴を遡って見るAPIは今後追加予定です)。
          </p>

          <div className="timeline-list">
            {timelineEntries.length === 0 && <p className="incident-empty-state">報告履歴はまだありません</p>}
            {timelineEntries.map(({ shelter, observation }) => (
              <TimelineRow
                key={observation.id}
                observedAt={observation.observed_at}
                shelter={shelter}
                reporterName={observation.reporter_name}
                urgency={observation.urgency}
                summary={observation.memo}
                source={observation.source}
              />
            ))}
          </div>
        </section>
      </main>
    </>
  );
}
