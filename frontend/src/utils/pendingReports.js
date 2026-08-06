import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

/**
 * この端末にまだサーバーへ送信できていない(オフラインキューに保留中の)
 * 報告一覧を読み取るだけの関数(sentReportHistory.jsのgetSentReportHistory()と
 * 同じ役割)。書き込みは引き続きuseOfflineReportQueue.jsが担当する。
 */
export function getPendingReports() {
  return loadJson(STORAGE_KEYS.pendingReports, []);
}
