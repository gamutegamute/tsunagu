import Dashboard from "../components/Dashboard.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { useDashboardData } from "../hooks/useDashboardData.js";
import { useDashboardPolling } from "../hooks/useDashboardPolling.js";
import { mergeEmergencyDataIntoDashboard } from "../utils/emergencyPacket.js";
import AuthStatus from "../components/AuthStatus.jsx";

// 決定事項33-b: 自動更新の間隔。手動の「同期」ボタンとは独立して併存させる。
const DASHBOARD_POLL_INTERVAL_MS = 15_000;

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
 *
 * 決定事項33-b: 上記の手動ボタンに加え、15秒間隔の自動更新(ポーリング)も
 * 併存させる(useDashboardPolling)。タブが非表示の間はポーリングを止め、
 * 再度表示されたタイミングで即座に最新化する。
 */
export default function DashboardPage() {
  const shelters = useShelterList();
  const { dashboardItems, emergencyPackets, reloadDashboard } = useDashboardData();

  useDashboardPolling(reloadDashboard, DASHBOARD_POLL_INTERVAL_MS);

  const shelterStatusList = mergeEmergencyDataIntoDashboard(dashboardItems, emergencyPackets, shelters);

  return (
    <>
      <header className="topbar">
        <div>
          <img
            className="topbar-logo"
            src={`${import.meta.env.BASE_URL}logo/logo-horizontal.png`}
            alt="TSUNAGU"
          />
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
