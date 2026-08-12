import { useEffect, useState } from "react";
import { fetchShelters } from "../api.js";
import { loadCachedShelters, saveCachedShelters } from "../utils/shelterCache.js";

// APIが失敗した場合・避難所が1件も登録されていない場合の最終フォールバック。
// (元のApp.jsxの catch ハンドラと同じ値)
const FALLBACK_SHELTERS = [{ id: "AIT001", name: "体育館" }];

/**
 * 避難所一覧を取得するだけのフック。
 * 取得に失敗した場合、または結果が0件だった場合は、最低限フォームが使えるように
 * フォールバックの避難所を1件返す。
 */
export function useShelterList() {
  const [shelters, setShelters] = useState(() => {
    const cachedShelters = loadCachedShelters();
    return cachedShelters.length > 0 ? cachedShelters : FALLBACK_SHELTERS;
  });

  useEffect(() => {
    let disposed = false;

    async function reloadShelters() {
      try {
        const items = await fetchShelters();
        if (!disposed && items.length > 0) {
          saveCachedShelters(items);
          setShelters(items);
        }
      } catch {
        // Keep the last successfully fetched shelter list for offline startup.
      }
    }

    void reloadShelters();
    window.addEventListener("online", reloadShelters);
    return () => {
      disposed = true;
      window.removeEventListener("online", reloadShelters);
    };
  }, []);

  return shelters;
}
