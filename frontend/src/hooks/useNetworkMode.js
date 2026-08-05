import { useCallback, useEffect, useRef, useState } from "react";

const PROBE_INTERVAL_MS = 10_000;
const PROBE_TIMEOUT_MS = 3_000;

async function canReachBackend() {
  if (!navigator.onLine) return false;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(`/health?probe=${Date.now()}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function useNetworkMode(onBackOnline) {
  const [networkMode, setNetworkModeState] = useState("offline");
  const modeRef = useRef("offline");
  const onlineRef = useRef(false);
  const onBackOnlineRef = useRef(onBackOnline);
  onBackOnlineRef.current = onBackOnline;

  const setNetworkMode = useCallback((mode) => {
    const wasOnline = onlineRef.current;
    modeRef.current = mode;
    onlineRef.current = mode === "normal";
    setNetworkModeState(mode);
    // 「オフライン」「非常時」から手動で「通常」に切り替えたときも、
    // 自動検知で復旧したときと同様に未送信データを再送する。
    // 「通常」から「通常」(変化なし)のときは呼ばない。
    if (mode === "normal" && !wasOnline) {
      onBackOnlineRef.current();
    }
  }, []);

  useEffect(() => {
    let disposed = false;

    async function probe() {
      const reachable = await canReachBackend();
      if (disposed || modeRef.current === "emergency") return;

      const wasOnline = onlineRef.current;
      onlineRef.current = reachable;
      modeRef.current = reachable ? "normal" : "offline";
      setNetworkModeState(modeRef.current);
      if (reachable && !wasOnline) await onBackOnlineRef.current();
    }

    function handleOffline() {
      if (modeRef.current === "emergency") return;
      onlineRef.current = false;
      modeRef.current = "offline";
      setNetworkModeState("offline");
    }

    function handleResume() {
      if (document.visibilityState === "visible") probe();
    }

    probe();
    const intervalId = window.setInterval(probe, PROBE_INTERVAL_MS);
    window.addEventListener("online", probe);
    window.addEventListener("offline", handleOffline);
    window.addEventListener("focus", probe);
    document.addEventListener("visibilitychange", handleResume);
    return () => {
      disposed = true;
      window.clearInterval(intervalId);
      window.removeEventListener("online", probe);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("focus", probe);
      document.removeEventListener("visibilitychange", handleResume);
    };
  }, []);

  return [networkMode, setNetworkMode];
}
