/**
 * localStorageからJSONを読み込む。値がない/壊れている場合は fallback を返す。
 * (元のApp.jsx内 loadJson をそのまま移動しただけで、中身は変えていない)
 */
export function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}
