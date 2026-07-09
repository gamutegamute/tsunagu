/** 報告先の避難所を選ぶプルダウン。 */
export default function ShelterSelectField({ shelters, selectedShelterId, onChange }) {
  return (
    <label>
      避難所
      <select value={selectedShelterId} onChange={(event) => onChange(event.target.value)} required>
        {shelters.map((shelter) => (
          <option key={shelter.id} value={shelter.id}>
            {shelter.id} - {shelter.name}
          </option>
        ))}
      </select>
    </label>
  );
}
