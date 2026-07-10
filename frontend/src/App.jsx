import { useEffect, useState } from "react";
import NetworkModeSwitcher from "./components/NetworkModeSwitcher.jsx";
import FieldReportForm from "./components/FieldReportForm.jsx";
import Dashboard from "./components/Dashboard.jsx";
import PacketsPanel from "./components/PacketsPanel.jsx";
import { useShelterList } from "./hooks/useShelterList.js";
import { useNetworkMode } from "./hooks/useNetworkMode.js";
import { useOfflineReportQueue } from "./hooks/useOfflineReportQueue.js";
import { useDashboardData } from "./hooks/useDashboardData.js";
import { createObservation } from "./api.js";
import { buildEmergencyPacket, decideLocalStatus, decideLocalRequestCode } from "./utils/emergencyPacket.js";
import { STORAGE_KEYS } from "./utils/storageKeys.js";

export default function App() {
  const shelters = useShelterList();
  const { pendingReportCount, addReportToPendingQueue, sendPendingReports } = useOfflineReportQueue();
  const { dashboardItems, emergencyPackets, reloadDashboard } = useDashboardData();
  const [lastPacket, setLastPacket] = useState("");

  // 通信が復活したら、保留中の報告を再送してからダッシュボードを更新する
  const [networkMode, setNetworkMode] = useNetworkMode(() => {
    sendPendingReports().then(reloadDashboard);
  });

  const isOnline = networkMode === "normal";
  const isEmergency = networkMode === "emergency";

  // 起動直後に一度ダッシュボードを読み込み、Service Workerを登録する
  useEffect(() => {
    reloadDashboard();

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/service-worker.js");
    }
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
      client_event_id: crypto.randomUUID(),
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
      } catch (error) {
        addReportToPendingQueue(payload);
      }
    } else {
      addReportToPendingQueue(payload);

      if (isEmergency) {
        // 非常時は通信量を抑えるため、詳細な報告は送らずLoRa向けの最低限パケットだけ組み立てる
        const status = decideLocalStatus(payload);
        setLastPacket(buildEmergencyPacket(payload, status, decideLocalRequestCode(payload, status)));
      }
    }

    await reloadDashboard();
  }

  function handleSyncButtonClick() {
    sendPendingReports().then(reloadDashboard);
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>ShelterOS</h1>
          <p>通信が途絶えても、現場の状況は途絶えない。</p>
        </div>
        <NetworkModeSwitcher networkMode={networkMode} onChangeMode={setNetworkMode} />
      </header>

      <main className="layout">
        <FieldReportForm
          shelters={shelters}
          networkMode={networkMode}
          pendingReportCount={pendingReportCount}
          onSubmitReport={handleSubmitReport}
        />
        <Dashboard shelterStatusList={dashboardItems} onSyncButtonClick={handleSyncButtonClick} />
        <PacketsPanel lastPacket={lastPacket} emergencyPackets={emergencyPackets} />
      </main>
    </>
  );
}
