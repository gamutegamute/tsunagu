import { useEffect, useState } from "react";
import { fetchShelters } from "../api.js";

// APIが失敗した場合・避難所が1件も登録されていない場合の最終フォールバック。
// (元のApp.jsxの catch ハンドラと同じ値)
const FALLBACK_SHELTERS = [{ id: "AIT001", name: "体育館" }];

/**
 * 避難所一覧を取得するだけのフック。
 * 取得に失敗した場合、または結果が0件だった場合は、最低限フォームが使えるように
 * フォールバックの避難所を1件返す。
 */
export function useShelterList() {
  const [shelters, setShelters] = useState([]);

  useEffect(() => {
    fetchShelters()
      .then((items) => setShelters(items.length > 0 ? items : FALLBACK_SHELTERS))
      .catch(() => setShelters(FALLBACK_SHELTERS));
  }, []);

  return shelters;
}
