import { useEffect, useRef } from "react";

const DEFAULT_INTERVAL_MS = 15_000;

/**
 * 決定事項33-b: 一定間隔で自動的にコールバック(reloadDashboard等)を実行する
 * ポーリングフック。手動更新ボタン(同期ボタン)とは独立して併存させる想定で、
 * このフック自体は「自動実行のスケジューリング」にだけ責任を持つ。
 *
 * タブが非表示(document.visibilityState !== "visible")の間は無駄な自動更新を
 * 止め、再度表示されたタイミングで即座に最新化してからポーリングを再開する。
 */
export function useDashboardPolling(callback, intervalMs = DEFAULT_INTERVAL_MS) {
  // callbackが毎レンダーで新しい関数になっても、intervalを張り直さずに済むよう
  // refに保持する(useNetworkMode.jsのonBackOnlineRefと同じ考え方)。
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    let intervalId = null;

    function startPolling() {
      if (intervalId !== null) return;
      intervalId = window.setInterval(() => callbackRef.current(), intervalMs);
    }

    function stopPolling() {
      if (intervalId === null) return;
      window.clearInterval(intervalId);
      intervalId = null;
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        callbackRef.current();
        startPolling();
      } else {
        stopPolling();
      }
    }

    callbackRef.current();
    startPolling();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [intervalMs]);
}
