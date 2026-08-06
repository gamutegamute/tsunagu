import { useCallback, useRef, useState } from "react";
import { fetchDashboard, fetchEmergencyPackets } from "../api.js";
import { loadJson } from "../utils/localJson.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";
import { recordDashboardSnapshot } from "../utils/shelterObservationHistory.js";

/**
 * 本部ダッシュボード(避難所一覧・Emergency Packets)のデータを読み込むフック。
 *
 * オンライン時は最新データを取得し、次回オフラインになったときのために
 * localStorage へキャッシュしておく。取得に失敗した場合(オフライン時)は、
 * 前回キャッシュしておいたデータを代わりに表示する。
 *
 * 決定事項34-c: 自動更新(ポーリング)と手動「同期」ボタンの両方が
 * reloadDashboardを呼び得るため、実行中に重ねて呼ばれた場合は新規リクエストを
 * 開始せず、進行中のPromiseをそのまま返す(in-flightガード)。これにより、
 * 遅いレスポンスが後から返ってきて新しいデータを上書きする事態を防ぐ。
 */
export function useDashboardData() {
  const [dashboardItems, setDashboardItems] = useState(() => loadJson(STORAGE_KEYS.cachedDashboard, []));
  const [emergencyPackets, setEmergencyPackets] = useState([]);
  const inFlightRef = useRef(null);

  function showAndCacheDashboard(items) {
    localStorage.setItem(STORAGE_KEYS.cachedDashboard, JSON.stringify(items));
    setDashboardItems(items);
  }

  const reloadDashboard = useCallback(() => {
    if (inFlightRef.current) return inFlightRef.current;

    const promise = (async () => {
      try {
        const items = await fetchDashboard();
        showAndCacheDashboard(items);
        recordDashboardSnapshot(items);
        setEmergencyPackets(await fetchEmergencyPackets());
      } catch (error) {
        showAndCacheDashboard(loadJson(STORAGE_KEYS.cachedDashboard, []));
      }
    })().finally(() => {
      inFlightRef.current = null;
    });

    inFlightRef.current = promise;
    return promise;
  }, []);

  return { dashboardItems, emergencyPackets, reloadDashboard };
}
