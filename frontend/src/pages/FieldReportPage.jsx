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

/**
 * 現場報告画面(モバイル向け、/field-report)。
 *
 * 決定事項21・27・29の通り、通信状態バナー(StatusHeroBanner、FieldReportForm内)は
 * このページに閉じており、Dashboard側(/dashboard)には表示しない。通信状態は
 * すべて自動判定(useNetworkMode)で、手動切り替えボタンは存在しない。
 *
 * 決定事項29: T-Beamが配信する非常用ページはこのクラウド版アプリとは完全に別サイト
 * であり、ブラウザのJavaScriptから直接LoRa送信をトリガーすることはできない。その
 * ため、このアプリ側は「オフラインと判定されてから10秒経ったら『LoRa使用可』の
 * 状態を画面に表示し、T-Beamの非常用Wi-Fi(名前が「TSUNAGU-」で始まるもの)への案内を出す」
 * ところまでを担当し、実際のLoRa送信処理・送信ボタンはここには実装しない
 * (以前実装していたsendEmergencyPacket/loraEmergencySend.jsによる送信トリガーは
 * この決定事項により削除した)。Wi-Fi名はファームの版や端末によって異なるため、
 * 画面では特定の名前を出さず、「TSUNAGU-」で始まることだけを案内する。
 *
 * Field ReportとHeadquarters Dashboardは別デバイス(現場のスマホ / 本部のPC)で
 * 開かれる前提のため、この端末のオフライン報告キューをDashboard側へ引き継ぐ
 * 手段はない(Reactの状態はページ・デバイスをまたいで共有できないため)。
 */
export default function FieldReportPage() {
  const shelters = useShelterList();
  const { pendingReportCount, isSyncing, syncError, addReportToPendingQueue, sendPendingReports } = useOfflineReportQueue();

  // 通信が復活したら、この端末の保留中の報告を再送する
  const [networkMode, offlinePhase] = useNetworkMode(() => {
    void sendPendingReports();
  });

  const isOnline = networkMode === "normal";

  async function handleSubmitReport({ reporterName, shelterId, peopleCount, waterStock, urgency, memo, clientEventId, observedAt }) {
    const trimmedReporterName = reporterName.trim();
    try {
      if (trimmedReporterName) localStorage.setItem(STORAGE_KEYS.reporterName, trimmedReporterName);
      setActiveShelter(shelterId);
    } catch { /* Preference storage must not block the durable report. */ }

    const payload = {
      reporter_name: trimmedReporterName,
      shelter_id: shelterId,
      client_event_id: clientEventId,
      people_count: peopleCount,
      water_stock: waterStock,
      urgency,
      memo,
      observed_at: observedAt,
      source: networkMode === "offline" ? "offline" : "web",
    };

    if (isOnline) {
      try {
        await createObservation(payload);
      } catch (error) {
        if (error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) throw error;
        await addReportToPendingQueue(payload, error);
        return "queued";
      }
      try { addSentReportToHistory({ shelterId, urgency, observedAt: payload.observed_at }); } catch { /* Already accepted by API. */ }
      return "sent";
    }

    // オフライン中は常に未送信キューへ保存し、通信復旧後に通常APIで再送する。
    // 決定事項29: 実際のLoRa送信はT-Beam専用ページの担当のため、ここでは行わない。
    await addReportToPendingQueue(payload);
    return "queued";
  }

  return (
    <>
      <header className="topbar">
        <div>
          <img
            className="topbar-logo"
            src={`${import.meta.env.BASE_URL}logo/logo-horizontal.png`}
            alt="TSUNAGU"
          />
          <p>通信が途絶えても、現場の状況は途絶えない。</p>
        </div>
        <div className="topbar-right-group">
          <AuthStatus />
          <FieldReportNavButtons />
        </div>
      </header>

      <main className="layout-mobile">
        {syncError && <p role="alert">{syncError}</p>}
        <FieldReportForm
          shelters={shelters}
          networkMode={networkMode}
          offlinePhase={offlinePhase}
          pendingReportCount={pendingReportCount}
          isSyncing={isSyncing}
          onSyncPendingReports={sendPendingReports}
          onSubmitReport={handleSubmitReport}
        />
      </main>
    </>
  );
}
