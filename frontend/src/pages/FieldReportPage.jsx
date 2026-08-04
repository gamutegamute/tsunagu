import NetworkModeSwitcher from "../components/NetworkModeSwitcher.jsx";
import FieldReportForm from "../components/FieldReportForm.jsx";
import FieldReportNavButtons from "../components/FieldReportNavButtons.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useNetworkMode } from "../hooks/useNetworkMode.js";
import { useOfflineReportQueue } from "../hooks/useOfflineReportQueue.js";
import { createObservation } from "../api.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";
import { setActiveShelter } from "../utils/activeShelter.js";
import { addSentReportToHistory } from "../utils/sentReportHistory.js";
import AuthStatus from "../components/AuthStatus.jsx";
import { createClientEventId } from "../utils/clientEventId.js";

/**
 * 現場報告画面(モバイル向け、/field-report)。
 *
 * 決定事項21の通り、通信状態インジケーター(NetworkModeSwitcher)と
 * オフライン/非常時バナー(StatusHeroBanner、FieldReportForm内)は
 * このページに閉じており、Dashboard側(/dashboard)には表示しない。
 *
 * Field ReportとHeadquarters Dashboardは別デバイス(現場のスマホ / 本部のPC)で
 * 開かれる前提のため、この端末のオフライン報告キューをDashboard側へ引き継ぐ
 * 手段はない(Reactの状態はページ・デバイスをまたいで共有できないため)。
 */
export default function FieldReportPage() {
  const shelters = useShelterList();
  const { pendingReportCount, addReportToPendingQueue, sendPendingReports } = useOfflineReportQueue();

  // 通信が復活したら、この端末の保留中の報告を再送する
  const [networkMode, setNetworkMode] = useNetworkMode(() => {
    sendPendingReports();
  });

  const isOnline = networkMode === "normal";

  async function handleSubmitReport({ reporterName, shelterId, peopleCount, waterStock, urgency, memo }) {
    const trimmedReporterName = reporterName.trim();
    if (trimmedReporterName) {
      localStorage.setItem(STORAGE_KEYS.reporterName, trimmedReporterName);
    }

    // 決定事項23: 避難所を選んで報告するたびに「アクティブ避難所」を更新する
    setActiveShelter(shelterId);

    const payload = {
      reporter_name: trimmedReporterName,
      shelter_id: shelterId,
      client_event_id: createClientEventId(),
      people_count: peopleCount,
      water_stock: waterStock,
      urgency,
      memo,
      observed_at: new Date().toISOString(),
      source: networkMode === "offline" || networkMode === "emergency" ? "offline" : "web",
    };

    if (isOnline) {
      try {
        await createObservation(payload);
        addSentReportToHistory({ shelterId, urgency, observedAt: payload.observed_at });
      } catch (error) {
        addReportToPendingQueue(payload);
      }
    } else {
      addReportToPendingQueue(payload);
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>TSUNAGU</h1>
          <p>通信が途絶えても、現場の状況は途絶えない。</p>
        </div>
        <div className="topbar-right-group">
          <AuthStatus />
          <FieldReportNavButtons />
          <NetworkModeSwitcher networkMode={networkMode} onChangeMode={setNetworkMode} />
        </div>
      </header>

      <main className="layout-mobile">
        <FieldReportForm
          shelters={shelters}
          networkMode={networkMode}
          pendingReportCount={pendingReportCount}
          onSubmitReport={handleSubmitReport}
        />
      </main>
    </>
  );
}
