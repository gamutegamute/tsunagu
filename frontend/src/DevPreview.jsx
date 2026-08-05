import { useEffect } from "react";
import FieldReportForm from "./components/FieldReportForm.jsx";
import Dashboard from "./components/Dashboard.jsx";
import { useShelterList } from "./hooks/useShelterList.js";
import { useNetworkMode } from "./hooks/useNetworkMode.js";
import { useOfflineReportQueue } from "./hooks/useOfflineReportQueue.js";
import { useDashboardData } from "./hooks/useDashboardData.js";
import { createObservation } from "./api.js";
import { STORAGE_KEYS } from "./utils/storageKeys.js";
import { createClientEventId } from "./utils/clientEventId.js";

/**
 * 開発確認用プレビューページ。本部権限でURLを直接開いた場合だけ表示する。
 *
 * Field Report(モバイル幅)とHeadquarters Dashboard(PC幅)を実寸に近いフレーム幅で
 * 並べて表示し、開発中に両方の見た目を同時に確認できるようにする。
 */
export default function DevPreview() {
  const shelters = useShelterList();
  const { pendingReportCount, addReportToPendingQueue, sendPendingReports } = useOfflineReportQueue();
  const { dashboardItems, reloadDashboard } = useDashboardData();
  const [networkMode] = useNetworkMode(() => {
    sendPendingReports().then(reloadDashboard);
  });

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmitReport({ reporterName, shelterId, peopleCount, waterStock, urgency, memo }) {
    const trimmedReporterName = reporterName.trim();
    if (trimmedReporterName) {
      localStorage.setItem(STORAGE_KEYS.reporterName, trimmedReporterName);
    }

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

    try {
      await createObservation(payload);
    } catch (error) {
      addReportToPendingQueue(payload);
    }

    await reloadDashboard();
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
            <FieldReportForm
              shelters={shelters}
              networkMode={networkMode}
              pendingReportCount={pendingReportCount}
              onSubmitReport={handleSubmitReport}
            />
          </div>
        </div>

        <div className="dev-preview-frame dev-preview-frame-desktop">
          <p className="dev-preview-frame-label">PC・1920px</p>
          <div className="dev-preview-frame-body">
            <Dashboard shelterStatusList={dashboardItems} onSyncButtonClick={handleSyncButtonClick} />
          </div>
        </div>
      </div>
    </div>
  );
}
