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

  const refreshPendingReportCount = useCallback(async () => {
    const count = await getPendingReportCount();
    setPendingReportCount(count);
    return count;
  }, []);

  useEffect(() => {
    void refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const addReportToPendingQueue = useCallback(async (report) => {
    await addPendingReport(report);
    void requestPersistentStorage();
    await refreshPendingReportCount();
  }, [refreshPendingReportCount]);

  const sendPendingReports = useCallback(async () => {
    if (syncInProgress.current) return;

    syncInProgress.current = true;
    setIsSyncing(true);
    try {
      const queue = await getPendingReports();
      for (const report of queue) {
        try {
          await createObservation(report);
          await removePendingReport(report.client_event_id);
          addSentReportToHistory({
            shelterId: report.shelter_id ?? report.shelter_code,
            urgency: report.urgency,
            observedAt: report.observed_at,
          });
        } catch {
          // Failed reports remain in IndexedDB for the next sync attempt.
        }
      }
      await refreshPendingReportCount();
    } finally {
      syncInProgress.current = false;
      setIsSyncing(false);
    }
  }, [refreshPendingReportCount]);

  return { pendingReportCount, isSyncing, addReportToPendingQueue, sendPendingReports };
}
