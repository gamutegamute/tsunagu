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
  const [pendingReportCount, setPendingReportCount] = useState(null);
  const [storageError, setStorageError] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);
  const syncInProgress = useRef(false);
  const attempts = useRef(new Map());
  const deliveries = useRef(new Map());
  const [syncError, setSyncError] = useState("");
  const [scheduleVersion, setScheduleVersion] = useState(0);

  const refreshPendingReportCount = useCallback(async () => {
    try {
      const count = await getPendingReportCount();
      setPendingReportCount(count);
      setStorageError("");
      return count;
    } catch (error) {
      setStorageError(error.message);
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const addReportToPendingQueue = useCallback(async (report, initialError) => {
    await addPendingReport(report);
    if (initialError) attempts.current.set(report.client_event_id, {
      failures: 1, blocked: initialError.status >= 400 && initialError.status < 500 && ![408, 429].includes(initialError.status),
      nextAt: Date.now() + Math.max(5000, initialError.retryAfterMs || 0),
    });
    void requestPersistentStorage().catch(() => {});
    await refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const sendReport = useCallback((report) => {
    const id = report.client_event_id;
    if (deliveries.current.has(id)) return deliveries.current.get(id);
    const promise = (async () => {
      await createObservation(report);
      await removePendingReport(id);
      attempts.current.delete(id);
      try { addSentReportToHistory({ shelterId: report.shelter_id ?? report.shelter_code, urgency: report.urgency, observedAt: report.observed_at }); }
      catch { /* The server has accepted the report; history is optional. */ }
      await refreshPendingReportCount();
    })().finally(() => deliveries.current.delete(id));
    deliveries.current.set(id, promise);
    return promise;
  }, [refreshPendingReportCount]);

  const sendPendingReports = useCallback(async () => {
    if (syncInProgress.current) return;

    syncInProgress.current = true;
    setIsSyncing(true);
    try {
      let queue;
      try { queue = await getPendingReports(); }
      catch (error) { setStorageError(error.message); queue = error.reports ?? []; }
      for (const report of queue) {
        const previous = attempts.current.get(report.client_event_id);
        if (previous?.blocked || previous?.nextAt > Date.now()) continue;
        try {
          await sendReport(report);
        } catch (error) {
          const blocked = error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status);
          const failures = (previous?.failures || 0) + 1;
          const delay = Math.max(Math.min(5000 * 2 ** Math.min(failures - 1, 6), 300000), error.retryAfterMs || 0);
          attempts.current.set(report.client_event_id, { blocked, failures, nextAt: Date.now() + delay });
          setSyncError(blocked ? "送信できない報告があります。入力内容またはログイン状態を確認してください。" : "一時的に送信できません。端末に保持して自動再送します。");
        }
      }
      if ((await refreshPendingReportCount()) === 0) setSyncError("");
    } finally {
      syncInProgress.current = false;
      setIsSyncing(false);
      setScheduleVersion((value) => value + 1);
    }
  }, [refreshPendingReportCount, sendReport]);

  const retryPendingReports = useCallback(async () => {
    // An explicit retry can follow corrected input/server configuration. Keep
    // transient Retry-After deadlines intact even for a manual sync.
    for (const [id, attempt] of attempts.current) {
      if (attempt.blocked) attempts.current.delete(id);
    }
    await sendPendingReports();
  }, [sendPendingReports]);

  useEffect(() => {
    if ((!pendingReportCount && !storageError) || isSyncing) return;
    const retryable = [...attempts.current.values()].filter((attempt) => !attempt.blocked);
    if (!storageError && attempts.current.size >= pendingReportCount && !retryable.length) return;
    const delay = storageError || attempts.current.size < pendingReportCount ? 5000
      : Math.max(5000, Math.min(...retryable.map((attempt) => attempt.nextAt - Date.now())));
    const timer = window.setTimeout(() => {
      if (navigator.onLine) void sendPendingReports().catch(() => setSyncError("未送信報告を読み出せません。再試行してください。"));
      else void refreshPendingReportCount().finally(() => setScheduleVersion((value) => value + 1));
    }, delay);
    return () => window.clearTimeout(timer);
  }, [pendingReportCount, storageError, isSyncing, scheduleVersion, sendPendingReports, refreshPendingReportCount]);

  return { pendingReportCount, isSyncing, syncError: storageError || syncError, addReportToPendingQueue, sendPendingReports, retryPendingReports, sendReport };
}
