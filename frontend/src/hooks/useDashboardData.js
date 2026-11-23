import { useCallback, useEffect, useRef, useState } from "react";
import { applyDashboardFreshness } from "../utils/dashboardFreshness.js";
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
  const [rawItems, setDashboardItems] = useState(() => loadJson(STORAGE_KEYS.cachedDashboard, []));
  const [now, setNow] = useState(Date.now);
  const [error, setError] = useState("");
  const [isCached, setIsCached] = useState(true);
  const [lastSuccessAt, setLastSuccessAt] = useState(() => loadJson(STORAGE_KEYS.cachedDashboardFetchedAt, null));
  const [emergencyPackets, setEmergencyPackets] = useState([]);
  const inFlightRef = useRef(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  function showAndCacheDashboard(items) {
    const fetchedAt = new Date().toISOString();
    try {
      localStorage.setItem(STORAGE_KEYS.cachedDashboard, JSON.stringify(items));
      localStorage.setItem(STORAGE_KEYS.cachedDashboardFetchedAt, JSON.stringify(fetchedAt));
      recordDashboardSnapshot(items);
    } catch { /* An optional cache failure must not hide a successful fetch. */ }
    setDashboardItems(items);
    setLastSuccessAt(fetchedAt);
    setIsCached(false);
    setNow(Date.now());
  }

  const reloadDashboard = useCallback(() => {
    if (inFlightRef.current) return inFlightRef.current;

    const promise = (async () => {
      try {
        const items = await fetchDashboard();
        if (!Array.isArray(items)) throw new Error("Invalid dashboard response");
        showAndCacheDashboard(items);
        setEmergencyPackets(await fetchEmergencyPackets());
        setError("");
        return true;
      } catch (error) {
        setIsCached(true);
        setNow(Date.now());
        setError("最新情報を取得できませんでした。保持している情報を表示しています。通信とログイン状態を確認してください。");
        return false;
      }
    })().finally(() => {
      inFlightRef.current = null;
    });

    inFlightRef.current = promise;
    return promise;
  }, []);

  return { dashboardItems: rawItems.map((item) => applyDashboardFreshness(item, now)), emergencyPackets, reloadDashboard, error, isCached, lastSuccessAt };
}
