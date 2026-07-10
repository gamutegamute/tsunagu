// Figma・決定事項17と同じく4段階(NORMAL/WARNING/ALERT/CRITICAL)。
// バックエンドのUrgency enumは対応予定だが現時点ではまだ3段階(NORMAL/HIGH/CRITICAL)のため、
// WARNING/ALERTを送信すると422になる可能性がある(バックエンド側で対応予定)。
const URGENCY_LEVELS = [
  { level: "NORMAL", label: "通常" },
  { level: "WARNING", label: "注意" },
  { level: "ALERT", label: "警戒" },
  { level: "CRITICAL", label: "重大" },
];

/** 緊急度を選ぶボタン群。 */
export default function UrgencyField({ urgency, onChange }) {
  return (
    <fieldset>
      <legend>緊急度</legend>
      <div className="urgency-grid">
        {URGENCY_LEVELS.map(({ level, label }) => (
          <button
            key={level}
            type="button"
            className={urgency === level ? `urgency active ${level.toLowerCase()}` : "urgency"}
            onClick={() => onChange(level)}
          >
            <span className="urgency-label-en">{level}</span>
            <span className="urgency-label-ja">{label}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}
