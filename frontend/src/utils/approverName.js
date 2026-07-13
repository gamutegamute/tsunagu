import { STORAGE_KEYS } from "./storageKeys.js";

/**
 * 本部(PC)ログイン画面(決定事項24)で入力された担当者名を、
 * 決定事項7・12の「承認者名」として扱うためのユーティリティ。
 *
 * Incidentの承認操作(今後実装予定)は、ここで保存された名前を
 * 承認者名としてそのまま使う想定。localStorageの生キーに直接触れる
 * 箇所を増やさないよう、読み書きはここに集約する。
 */

/** ログイン中の承認者名を取得する。未ログインの場合は null。 */
export function getApproverName() {
  return localStorage.getItem(STORAGE_KEYS.approverName);
}

/** ログイン時に入力された担当者名を、承認者名として保存する。 */
export function setApproverName(approverName) {
  localStorage.setItem(STORAGE_KEYS.approverName, approverName);
}

/** ログアウト相当。保存されている承認者名を消去する。 */
export function clearApproverName() {
  localStorage.removeItem(STORAGE_KEYS.approverName);
}

/** 本部PCとしてログイン済みかどうか。 */
export function isApproverLoggedIn() {
  return getApproverName() !== null;
}
