import { useCallback, useEffect, useRef, useState } from "react";
import { createObservation } from "../api.js";
import { addSentReportToHistory } from "../utils/sentReportHistory.js";
import {
  addPendingReport,
  getPendingReportCount,
  getPendingReports,
  removePendingReport,
  requestPersistentStorage,
} from "../utils/pendingReports.js";

/** 未送信報告を IndexedDB に保存し、回線復旧時に安全に再送する。 */
export function useOfflineReportQueue() {
  const [pendingReportCount, setPendingReportCount] = useState(0);
  const [isSyncing, setIsSyncing] = useState(false);
  const syncInProgress = useRef(false);
  const attempts = useRef(new Map());
  const [syncError, setSyncError] = useState("");
  const [scheduleVersion, setScheduleVersion] = useState(0);

  const refreshPendingReportCount = useCallback(async () => {
    const count = await getPendingReportCount();
    setPendingReportCount(count);
    return count;
  }, []);

  useEffect(() => {
    void refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const addReportToPendingQueue = useCallback(async (report, initialError) => {
    await addPendingReport(report);
    if (initialError) attempts.current.set(report.client_event_id, {
      failures: 1, blocked: false, nextAt: Date.now() + Math.max(5000, initialError.retryAfterMs || 0),
    });
    void requestPersistentStorage().catch(() => {});
    await refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const sendPendingReports = useCallback(async () => {
    if (syncInProgress.current) return;

    syncInProgress.current = true;
    setIsSyncing(true);
    try {
      const queue = await getPendingReports();
      for (const report of queue) {
        const previous = attempts.current.get(report.client_event_id);
        if (previous?.blocked || previous?.nextAt > Date.now()) continue;
        try {
          await createObservation(report);
          await removePendingReport(report.client_event_id);
          attempts.current.delete(report.client_event_id);
          try { addSentReportToHistory({
            shelterId: report.shelter_id ?? report.shelter_code,
            urgency: report.urgency,
            observedAt: report.observed_at,
          }); } catch { /* API acceptance and durable deletion already succeeded. */ }
        } catch (error) {
          const blocked = error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status);
          const failures = (previous?.failures || 0) + 1;
          const delay = Math.max(Math.min(5000 * 2 ** Math.min(failures - 1, 6), 300000), error.retryAfterMs || 0);
          attempts.current.set(report.client_event_id, { blocked, failures, nextAt: Date.now() + delay });
          setSyncError(blocked ? "送信できない報告があります。入力内容またはログイン状態を確認してください。" : "一時的に送信できません。端末に保持して自動再送します。");
        }
      }
      await refreshPendingReportCount();
      if ((await getPendingReportCount()) === 0) setSyncError("");
    } finally {
      syncInProgress.current = false;
      setIsSyncing(false);
      setScheduleVersion((value) => value + 1);
    }
  }, [refreshPendingReportCount]);

  useEffect(() => {
    if (!pendingReportCount || isSyncing) return;
    const retryable = [...attempts.current.values()].filter((attempt) => !attempt.blocked);
    if (attempts.current.size >= pendingReportCount && !retryable.length) return;
    const delay = attempts.current.size < pendingReportCount ? 5000
      : Math.max(5000, Math.min(...retryable.map((attempt) => attempt.nextAt - Date.now())));
    const timer = window.setTimeout(() => {
      if (navigator.onLine) void sendPendingReports().catch(() => setSyncError("未送信報告を読み出せません。再試行してください。"));
      else setScheduleVersion((value) => value + 1);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [pendingReportCount, isSyncing, scheduleVersion, sendPendingReports]);

  return { pendingReportCount, isSyncing, syncError, addReportToPendingQueue, sendPendingReports };
}
