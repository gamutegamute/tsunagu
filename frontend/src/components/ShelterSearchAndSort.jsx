const SORT_OPTIONS = [
  { value: "ADDED_ORDER", label: "追加順" },
  { value: "PEOPLE_DESC", label: "人数(多い順)" },
  { value: "PEOPLE_ASC", label: "人数(少ない順)" },
];

/** 避難所名・IDでの検索欄と、並び替え(決定事項17)のプルダウン。 */
export default function ShelterSearchAndSort({ searchText, onSearchTextChange, sortOrder, onSortOrderChange }) {
  return (
    <div className="search-and-sort-row">
      <div className="search-box">
        <span aria-hidden="true">🔍</span>
        <input
          type="text"
          placeholder="避難所名・IDで検索"
          value={searchText}
          onChange={(event) => onSearchTextChange(event.target.value)}
        />
      </div>

      <label className="sort-dropdown">
        <span className="sort-dropdown-label">並び順:</span>
        <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)}>
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
