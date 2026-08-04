import { useEffect } from "react";
import Dashboard from "../components/Dashboard.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useDashboardData } from "../hooks/useDashboardData.js";
import { mergeEmergencyDataIntoDashboard } from "../utils/emergencyPacket.js";
import AuthStatus from "../components/AuthStatus.jsx";

/**
 * 本部ダッシュボード画面(PC向け、/dashboard)。
 *
 * 決定事項21の通り、現場(Field Report)側の通信状態インジケーター・
 * オフライン/非常時バナーはここには表示しない。PC自体のオンライン状態を示す
 * 仕組み(決定事項24関連)は現時点でコード上に見当たらないため、今回は追加していない。
 *
 * 「同期」ボタンは、この端末の保留中報告キューを再送するものではなく
 * (Field Reportとは別デバイス運用のため、そのキューはここにはない)、
 * サーバーから最新の状況一覧を取得し直すだけの単純な再読み込みボタンとする。
 */
export default function DashboardPage() {
  const shelters = useShelterList();
  const { dashboardItems, emergencyPackets, reloadDashboard } = useDashboardData();

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const shelterStatusList = mergeEmergencyDataIntoDashboard(dashboardItems, emergencyPackets, shelters);

  return (
    <>
      <header className="topbar">
        <div>
          <h1>ShelterOS</h1>
          <p>本部ダッシュボード</p>
        </div>
        <AuthStatus />
      </header>

      <main className="layout-desktop">
        <Dashboard shelterStatusList={shelterStatusList} onSyncButtonClick={reloadDashboard} />
      </main>
    </>
  );
}
