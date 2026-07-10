/** 現場の状況を自由に書けるメモ欄。 */
export default function MemoField({ memo, onChange }) {
  return (
    <label>
      メモ
      <textarea
        rows={3}
        placeholder="気づいたことを自由に記入してください"
        value={memo}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
