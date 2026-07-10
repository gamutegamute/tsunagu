const MODES = [
  { id: "normal", label: "通常" },
  { id: "offline", label: "オフライン" },
  { id: "emergency", label: "非常時" },
];

/**
 * ヘッダーにある、通信状態を手動で切り替えるボタン群。
 * 「通常」「オフライン」は本来ブラウザが自動検知するが、デモ・動作確認のために
 * 手動でも切り替えられるようにしている(「非常時」は自動検知の仕組みがないため、常に手動)。
 */
export default function NetworkModeSwitcher({ networkMode, onChangeMode }) {
  return (
    <div className="mode-controls" aria-label="通信状態">
      {MODES.map((mode) => (
        <button
          key={mode.id}
          type="button"
          className={networkMode === mode.id ? "mode-button active" : "mode-button"}
          onClick={() => onChangeMode(mode.id)}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
