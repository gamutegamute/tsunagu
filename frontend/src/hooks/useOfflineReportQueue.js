import { useState } from "react";
import { createObservation } from "../api.js";
import { loadJson } from "../utils/localJson.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";
import { addSentReportToHistory } from "../utils/sentReportHistory.js";

function readPendingReportsFromStorage() {
  return loadJson(STORAGE_KEYS.pendingReports, []);
}

function savePendingReportsToStorage(reports) {
  localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify(reports));
}

/**
 * 送信できなかった報告を端末に一時保存しておき、後でまとめて再送信するための
 * フック(オフライン対応の中心となるロジック)。
 *
 * 1. 送信に失敗した報告は、消さずに localStorage の中に「保留キュー」として貯めておく
 * 2. 通信が復活したタイミングで、保留キューの中身を1件ずつ再送信する
 * 3. 再送信に成功した分だけキューから取り除き、失敗した分はキューに残す
 */
export function useOfflineReportQueue() {
  const [pendingReportCount, setPendingReportCount] = useState(() => readPendingReportsFromStorage().length);

  /** 送信に失敗した報告をキューの末尾に追加する */
  function addReportToPendingQueue(report) {
    const queue = [...readPendingReportsFromStorage(), report];
    savePendingReportsToStorage(queue);
    setPendingReportCount(queue.length);
  }

  /** キューに溜まっている報告を1件ずつ送信し、失敗した分だけキューに残す */
  async function sendPendingReports() {
    const queue = readPendingReportsFromStorage();
    const reportsStillPending = [];

    for (const report of queue) {
      try {
        await createObservation(report);
        addSentReportToHistory({
          shelterId: report.shelter_id ?? report.shelter_code,
          urgency: report.urgency,
          observedAt: report.observed_at,
        });
      } catch (error) {
        reportsStillPending.push(report);
      }
    }

    savePendingReportsToStorage(reportsStillPending);
    setPendingReportCount(reportsStillPending.length);
  }

  return { pendingReportCount, addReportToPendingQueue, sendPendingReports };
}
