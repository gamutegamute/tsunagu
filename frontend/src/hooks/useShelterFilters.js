import { useMemo, useState } from "react";

/**
 * 状況一覧タブの「検索・絞り込み・並び替え」をまとめて管理するフック(決定事項17)。
 *
 * 元の避難所リストは変更せず、表示用に「絞り込み・並び替え済みのリスト」を
 * 別途計算して返す。checkbox/chipの選択状態はこのフックの中だけで持つ。
 */
export function useShelterFilters(shelterStatusList) {
  const [searchText, setSearchText] = useState("");
  const [urgencyFilter, setUrgencyFilter] = useState("ALL"); // ALL | NORMAL | WARNING | ALERT | CRITICAL
  const [requestCodeFilter, setRequestCodeFilter] = useState("ALL"); // ALL | HAS_REQUEST | NO_REQUEST
  const [sortOrder, setSortOrder] = useState("ADDED_ORDER"); // ADDED_ORDER | PEOPLE_DESC | PEOPLE_ASC

  const filteredAndSortedList = useMemo(() => {
    const matchesSearchText = (shelterStatus) => {
      if (searchText.trim() === "") return true;
      const keyword = searchText.trim().toLowerCase();
      const { id, name } = shelterStatus.shelter;
      return id.toLowerCase().includes(keyword) || name.toLowerCase().includes(keyword);
    };

    const matchesUrgencyFilter = (shelterStatus) => {
      if (urgencyFilter === "ALL") return true;
      return shelterStatus.status === urgencyFilter;
    };

    const matchesRequestCodeFilter = (shelterStatus) => {
      if (requestCodeFilter === "ALL") return true;
      const hasRequest = shelterStatus.request_code !== null;
      return requestCodeFilter === "HAS_REQUEST" ? hasRequest : !hasRequest;
    };

    const filtered = shelterStatusList.filter(
      (shelterStatus) =>
        matchesSearchText(shelterStatus) && matchesUrgencyFilter(shelterStatus) && matchesRequestCodeFilter(shelterStatus),
    );

    if (sortOrder === "ADDED_ORDER") {
      return filtered; // 元の並び順(=避難所が追加された順)のまま
    }

    const peopleCountOf = (shelterStatus) => shelterStatus.latest_observation?.people_count ?? 0;
    const sorted = [...filtered].sort((a, b) =>
      sortOrder === "PEOPLE_DESC" ? peopleCountOf(b) - peopleCountOf(a) : peopleCountOf(a) - peopleCountOf(b),
    );
    return sorted;
  }, [shelterStatusList, searchText, urgencyFilter, requestCodeFilter, sortOrder]);

  return {
    searchText,
    setSearchText,
    urgencyFilter,
    setUrgencyFilter,
    requestCodeFilter,
    setRequestCodeFilter,
    sortOrder,
    setSortOrder,
    filteredAndSortedList,
  };
}
