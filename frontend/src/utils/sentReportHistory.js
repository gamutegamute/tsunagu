import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

const MAX_HISTORY_LENGTH = 50;

/**
 * この端末が実際にサーバーへ送信できた報告の履歴(決定事項22: 送信履歴)。
 * オフラインキューに退避しただけ(まだサーバーに届いていない)ものは含めない。
 */
export function getSentReportHistory() {
  return loadJson(STORAGE_KEYS.sentReportHistory, []);
}

export function addSentReportToHistory({ shelterId, urgency, observedAt }) {
  const history = [{ shelterId, urgency, observedAt, sentAt: new Date().toISOString() }, ...getSentReportHistory()].slice(
    0,
    MAX_HISTORY_LENGTH,
  );
  localStorage.setItem(STORAGE_KEYS.sentReportHistory, JSON.stringify(history));
}
