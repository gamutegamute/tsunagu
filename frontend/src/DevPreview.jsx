import { useEffect } from "react";
import FieldReportForm from "./components/FieldReportForm.jsx";
import Dashboard from "./components/Dashboard.jsx";
import { useShelterList } from "./hooks/useShelterList.js";
import { useNetworkMode } from "./hooks/useNetworkMode.js";
import { useOfflineReportQueue } from "./hooks/useOfflineReportQueue.js";
import { useDashboardData } from "./hooks/useDashboardData.js";
import { STORAGE_KEYS } from "./utils/storageKeys.js";
import DashboardFreshness from "./components/DashboardFreshness.jsx";

/**
 * 開発確認用プレビューページ。本部権限でURLを直接開いた場合だけ表示する。
 *
 * Field Report(モバイル幅)とHeadquarters Dashboard(PC幅)を実寸に近いフレーム幅で
 * 並べて表示し、開発中に両方の見た目を同時に確認できるようにする。
 */
export default function DevPreview() {
  const shelters = useShelterList();
  const { pendingReportCount, addReportToPendingQueue, sendPendingReports, sendReport, isSyncing, syncError } = useOfflineReportQueue();
  const { dashboardItems, reloadDashboard, ...freshness } = useDashboardData();
  const [networkMode, offlinePhase] = useNetworkMode(() => {
    sendPendingReports().then(reloadDashboard);
  });

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmitReport({ reporterName, shelterId, peopleCount, waterStock, urgency, memo, clientEventId, observedAt }) {
    const trimmedReporterName = reporterName.trim();
    try { if (trimmedReporterName) localStorage.setItem(STORAGE_KEYS.reporterName, trimmedReporterName); } catch { /* Optional preference. */ }

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

    await addReportToPendingQueue(payload);
    if (networkMode !== "normal") return "queued";
    try {
      await sendReport(payload);
    } catch (error) {
      await addReportToPendingQueue(payload, error);
      if (error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status)) throw error;
      return "queued";
    }

    await reloadDashboard();
    return "sent";
  }

  function handleSyncButtonClick() {
    sendPendingReports().then(reloadDashboard);
  }

  return (
    <div className="dev-preview">
      <p className="dev-preview-banner">
        開発確認用プレビュー(本番には存在しないページです) — 左: Field Report(モバイル幅) / 右: Headquarters
        Dashboard(PC幅)
      </p>
      <div className="dev-preview-frames">
        <div className="dev-preview-frame dev-preview-frame-mobile">
          <p className="dev-preview-frame-label">モバイル・390px</p>
          <div className="dev-preview-frame-body">
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
          </div>
        </div>

        <div className="dev-preview-frame dev-preview-frame-desktop">
          <p className="dev-preview-frame-label">PC・1920px</p>
          <div className="dev-preview-frame-body">
            <DashboardFreshness {...freshness} />
            <Dashboard shelterStatusList={dashboardItems} onSyncButtonClick={handleSyncButtonClick} />
          </div>
        </div>
      </div>
    </div>
  );
}
