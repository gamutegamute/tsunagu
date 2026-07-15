import { useEffect, useMemo, useState } from "react";
import { useDashboardData } from "./useDashboardData.js";
import { deriveIncidentsFromDashboard } from "../utils/incidents.js";

/**
 * 全避難所のインシデント一覧を取得するフック(決定事項2: 閲覧は全エリア可)。
 *
 * サーバーからは避難所ごとの最新状況(dashboardItems)を取得し、その中から
 * メモ入りの報告をIncidentとして抽出する。承認状態などのローカル状態
 * (incidentStore)はサーバーには存在しないため、refresh() を呼ぶたびに
 * localStorageから読み直して合成し直す。
 */
export function useIncidents() {
  const { dashboardItems, reloadDashboard } = useDashboardData();
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    reloadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const incidents = useMemo(
    () => deriveIncidentsFromDashboard(dashboardItems),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dashboardItems, refreshTick],
  );

  async function refresh() {
    await reloadDashboard();
    setRefreshTick((tick) => tick + 1);
  }

  /** サーバーへの再取得はせず、ローカル状態(承認結果など)だけを反映し直す。 */
  function refreshLocalState() {
    setRefreshTick((tick) => tick + 1);
  }

  return { incidents, refresh, refreshLocalState };
}
