import { useCallback, useEffect, useRef, useState } from "react";

const PROBE_INTERVAL_MS = 10_000;
const PROBE_TIMEOUT_MS = 3_000;
// 決定事項27: オフラインと判定されてから10秒間は通常のAPI再接続(/healthの
// 定期プロービング)を試み続け、それでも復旧しなければ「LoRa使用可」の内部
// 状態に自動的に切り替える(自動送信はしない。送信のトリガーは決定事項27参照)。
const LORA_AVAILABLE_DELAY_MS = 10_000;

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

/**
 * 通信状態の自動検知フック(決定事項27)。
 *
 * 画面表示上のモードは "normal" / "offline" の2つのみ。手動切り替えは廃止し、
 * すべて自動判定のみで遷移する。
 *
 * オフライン中は内部的に2段階のサブフェーズ(offlinePhase)を持つ:
 *   - "retrying": オフライン判定直後から10秒間、通常のAPI再接続を試み続ける段階
 *   - "lora-available": 10秒経っても復旧しなければ切り替わる、「LoRa使用可」の段階。
 *     ここに入っても自動でLoRa送信はしない。実際に送信するかどうかは、この段階中に
 *     ユーザーが報告する操作をしたときだけ呼び出し側(FieldReportPage)が判断する。
 *
 * この間も自動検知(定期プロービング・online/offlineイベント等)は止まらず、
 * 復旧すればフェーズに関わらずいつでも自動的に normal へ戻る。
 */
export function useNetworkMode(onBackOnline) {
  const [networkMode, setNetworkModeState] = useState("offline");
  const [offlinePhase, setOfflinePhase] = useState("retrying");
  // modeRef は「今まさにoffline遷移した瞬間かどうか」の判定専用。
  // 初期値をnullにしておくことで、マウント直後の最初のoffline判定も
  // 正しく新規遷移として扱われる(LoRa使用可タイマーが必ず開始される)。
  const modeRef = useRef(null);
  const onlineRef = useRef(false);
  const onBackOnlineRef = useRef(onBackOnline);
  onBackOnlineRef.current = onBackOnline;
  const loraAvailableTimerRef = useRef(null);

  const clearLoraAvailableTimer = useCallback(() => {
    if (loraAvailableTimerRef.current !== null) {
      window.clearTimeout(loraAvailableTimerRef.current);
      loraAvailableTimerRef.current = null;
    }
  }, []);

  const enterOffline = useCallback(() => {
    modeRef.current = "offline";
    onlineRef.current = false;
    setNetworkModeState("offline");
    setOfflinePhase("retrying");
    clearLoraAvailableTimer();
    loraAvailableTimerRef.current = window.setTimeout(() => {
      loraAvailableTimerRef.current = null;
      setOfflinePhase("lora-available");
    }, LORA_AVAILABLE_DELAY_MS);
  }, [clearLoraAvailableTimer]);

  const enterNormal = useCallback(() => {
    modeRef.current = "normal";
    onlineRef.current = true;
    setNetworkModeState("normal");
    setOfflinePhase("retrying");
    clearLoraAvailableTimer();
  }, [clearLoraAvailableTimer]);

  useEffect(() => {
    let disposed = false;

    async function probe() {
      const reachable = await canReachBackend();
      if (disposed) return;

      if (reachable) {
        const wasOnline = onlineRef.current;
        enterNormal();
        if (!wasOnline) await onBackOnlineRef.current();
      } else if (modeRef.current !== "offline") {
        // normalからの復旧待ち、またはマウント直後の初回判定のときだけ
        // 新規にoffline遷移する(LoRa使用可タイマーを起動する)。
        // 既にoffline中の場合はここで何もせず、進行中のタイマーに任せる。
        enterOffline();
      }
    }

    function handleOffline() {
      if (modeRef.current !== "offline") enterOffline();
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
      clearLoraAvailableTimer();
      window.clearInterval(intervalId);
      window.removeEventListener("online", probe);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("focus", probe);
      document.removeEventListener("visibilitychange", handleResume);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return [networkMode, offlinePhase];
}
