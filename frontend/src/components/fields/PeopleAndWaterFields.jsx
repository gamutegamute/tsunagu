/** 避難者数(人数)と水在庫(水)の入力欄。横並びの2列。 */
export default function PeopleAndWaterFields({ peopleCount, waterStock, onPeopleCountChange, onWaterStockChange }) {
  return (
    <div className="split">
      <label>
        人数(人)
        <input
          type="number"
          className="field-input-large"
          min="0"
          value={peopleCount}
          onChange={(event) => onPeopleCountChange(event.target.value)}
          required
        />
      </label>
      <label>
        水(L)
        <input
          type="number"
          className="field-input-large"
          min="0"
          value={waterStock}
          onChange={(event) => onWaterStockChange(event.target.value)}
          required
        />
      </label>
    </div>
  );
}
