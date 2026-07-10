// Figma・決定事項17: 緊急度は4段階(NORMAL/WARNING/ALERT/CRITICAL)を前提にする。
// バックエンドのUrgency enumが3段階(NORMAL/HIGH/CRITICAL)のままの間はCRITICALの
// 絞り込み結果が0件になりうるが、UI側は4段階を先取りして実装しておく。
const URGENCY_LEVELS = ["NORMAL", "WARNING", "ALERT", "CRITICAL"];

const REQUEST_CODE_OPTIONS = [
  { value: "ALL", label: "すべて" },
  { value: "HAS_REQUEST", label: "要請あり" },
  { value: "NO_REQUEST", label: "要請なし" },
];

/** 選べる・選ばれているを見た目で示すだけの小さなボタン(チップ)。 */
function FilterChip({ label, isActive, onClick }) {
  return (
    <button type="button" className={`filter-chip ${isActive ? "is-active" : ""}`} onClick={onClick}>
      {label}
    </button>
  );
}

/** 「緊急度」「要請コード」で状況一覧を絞り込むためのチップ列(決定事項17)。 */
export default function ShelterFilterChips({
  urgencyFilter,
  onUrgencyFilterChange,
  requestCodeFilter,
  onRequestCodeFilterChange,
}) {
  return (
    <div className="filter-chip-row">
      <span className="filter-chip-row-label">緊急度:</span>
      <FilterChip label="すべて" isActive={urgencyFilter === "ALL"} onClick={() => onUrgencyFilterChange("ALL")} />
      {URGENCY_LEVELS.map((level) => (
        <FilterChip
          key={level}
          label={level}
          isActive={urgencyFilter === level}
          onClick={() => onUrgencyFilterChange(level)}
        />
      ))}

      <span className="filter-divider" />

      <span className="filter-chip-row-label">要請コード:</span>
      {REQUEST_CODE_OPTIONS.map((option) => (
        <FilterChip
          key={option.value}
          label={option.label}
          isActive={requestCodeFilter === option.value}
          onClick={() => onRequestCodeFilterChange(option.value)}
        />
      ))}
    </div>
  );
}
