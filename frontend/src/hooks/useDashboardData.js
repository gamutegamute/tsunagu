import { useCallback, useState } from "react";
import { fetchDashboard, fetchEmergencyPackets } from "../api.js";
import { loadJson } from "../utils/localJson.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

/**
 * 本部ダッシュボード(避難所一覧・Emergency Packets)のデータを読み込むフック。
 *
 * オンライン時は最新データを取得し、次回オフラインになったときのために
 * localStorage へキャッシュしておく。取得に失敗した場合(オフライン時)は、
 * 前回キャッシュしておいたデータを代わりに表示する。
 */
export function useDashboardData() {
  const [dashboardItems, setDashboardItems] = useState(() => loadJson(STORAGE_KEYS.cachedDashboard, []));
  const [emergencyPackets, setEmergencyPackets] = useState([]);

  function showAndCacheDashboard(items) {
    localStorage.setItem(STORAGE_KEYS.cachedDashboard, JSON.stringify(items));
    setDashboardItems(items);
  }

  const reloadDashboard = useCallback(async () => {
    try {
      const items = await fetchDashboard();
      showAndCacheDashboard(items);
      setEmergencyPackets(await fetchEmergencyPackets());
    } catch (error) {
      showAndCacheDashboard(loadJson(STORAGE_KEYS.cachedDashboard, []));
    }
  }, []);

  return { dashboardItems, emergencyPackets, reloadDashboard };
}
