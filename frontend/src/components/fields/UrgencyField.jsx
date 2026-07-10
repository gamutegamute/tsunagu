// 現状は元のApp.jsxと同じ3段階(NORMAL/HIGH/CRITICAL)。
// 4段階(NORMAL/WARNING/ALERT/CRITICAL)への変更はStep 5で行う。
const URGENCY_LEVELS = ["NORMAL", "HIGH", "CRITICAL"];

/** 緊急度を選ぶボタン群。 */
export default function UrgencyField({ urgency, onChange }) {
  return (
    <fieldset>
      <legend>緊急度</legend>
      <div className="urgency-grid">
        {URGENCY_LEVELS.map((level) => (
          <button
            key={level}
            type="button"
            className={urgency === level ? `urgency active ${level.toLowerCase()}` : "urgency"}
            onClick={() => onChange(level)}
          >
            {level}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
