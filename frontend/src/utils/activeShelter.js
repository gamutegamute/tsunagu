import { STORAGE_KEYS } from "./storageKeys.js";

/**
 * 「アクティブ避難所」(決定事項23)。
 *
 * ログイン機能を持たないモバイル端末で「この端末が直近どの避難所を
 * 担当しているか」を推定するための軽量な仕組み。Field Reportで避難所を
 * 選んで送信するたびに更新し、Incidentの「対応済みにする」申請時の
 * デフォルト選択・本部側の目視確認(申請カードへの併記)に使う。
 */
export function getActiveShelter() {
  const id = localStorage.getItem(STORAGE_KEYS.activeShelter);
  return id || null;
}

export function setActiveShelter(shelterId) {
  if (!shelterId) return;
  localStorage.setItem(STORAGE_KEYS.activeShelter, shelterId);
}
