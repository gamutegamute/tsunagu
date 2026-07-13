import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

/**
 * 避難所のキャパシティ(決定事項9)。
 *
 * バックエンドのSheler.model/テーブルにキャパシティ用のカラムが無いため
 * (申し送り事項を参照)、フロント先行の暫定対応としてこの端末の
 * localStorageに保存する。本部PC間でも共有されない点に注意。
 */
export function getCapacity(shelterId) {
  const capacities = loadJson(STORAGE_KEYS.shelterCapacities, {});
  return capacities[shelterId] ?? null;
}

export function setCapacity(shelterId, capacity) {
  const capacities = loadJson(STORAGE_KEYS.shelterCapacities, {});
  capacities[shelterId] = capacity;
  localStorage.setItem(STORAGE_KEYS.shelterCapacities, JSON.stringify(capacities));
}
