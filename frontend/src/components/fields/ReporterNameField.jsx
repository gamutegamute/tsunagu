/** 報告者名を入力する欄。値の保存(送信時のlocalStorage書き込み)は呼び出し元が担当する。 */
export default function ReporterNameField({ reporterName, onChange }) {
  return (
    <label>
      報告者名
      <input
        type="text"
        placeholder="田中"
        value={reporterName}
        onChange={(event) => onChange(event.target.value)}
        required
      />
    </label>
  );
}
