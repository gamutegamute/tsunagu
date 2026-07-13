import { useState } from "react";
import { createShelter } from "../api.js";
import { setCapacity } from "../utils/shelterCapacity.js";

/**
 * 「避難所を追加」モーダル(決定事項9・13、Figma: 避難所追加・キャパシティ設定)。
 *
 * キャパシティは 床面積(㎡) ÷ 1.65㎡/人 が基本算出方法(決定事項9)。
 * バックエンドのShelterにはまだキャパシティ用のカラムが無いため
 * (申し送り事項を参照)、この端末のlocalStorageに保存する。
 */
export default function AddShelterModal({ onCancel, onCreated }) {
  const [name, setName] = useState("");
  const [shelterId, setShelterId] = useState("");
  const [capacity, setCapacityInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    setIsSubmitting(true);
    setErrorMessage("");
    try {
      // バックエンドは現状クライアント指定のIDを受け付けず、サーバー側で自動採番する
      // (申し送り事項を参照)。入力されたIDはこの端末の記録用に保持しておく。
      const created = await createShelter({ name: trimmedName, requested_id: shelterId.trim() || undefined });
      if (capacity.trim()) {
        setCapacity(created.id, Number(capacity));
      }
      onCreated(created);
    } catch (error) {
      setErrorMessage("登録に失敗しました。時間をおいて再度お試しください。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay modal-overlay-center" role="dialog" aria-modal="true">
      <form className="add-shelter-modal-card" onSubmit={handleSubmit}>
        <div className="add-shelter-modal-title-row">
          <div>
            <p className="bottom-sheet-title">避難所を追加</p>
            <p className="bottom-sheet-subtitle">キャパシティ(人数上限)もあわせて設定します</p>
          </div>
          <button type="button" className="modal-close-button" onClick={onCancel} aria-label="閉じる">
            ✕
          </button>
        </div>

        <label className="bottom-sheet-field">
          避難所名
          <input
            type="text"
            placeholder="例: 愛知工業大学 体育館"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>

        <label className="bottom-sheet-field">
          避難所ID
          <input
            type="text"
            placeholder="例: AIT001"
            value={shelterId}
            onChange={(event) => setShelterId(event.target.value)}
          />
        </label>

        <label className="bottom-sheet-field">
          キャパシティ(人数上限)
          <input
            type="number"
            min="0"
            placeholder="例: 170"
            value={capacity}
            onChange={(event) => setCapacityInput(event.target.value)}
          />
          <span className="bottom-sheet-hint">
            算出目安: 床面積(㎡) ÷ 1.65㎡/人(内閣府 避難所ガイドライン基準)。施設側で収容人数が定められている場合はその数値を優先してください。
          </span>
        </label>

        {errorMessage && <p className="form-error-message">{errorMessage}</p>}

        <div className="add-shelter-modal-footer">
          <button type="button" className="secondary-button" onClick={onCancel}>
            キャンセル
          </button>
          <button type="submit" className="primary-button" disabled={isSubmitting}>
            {isSubmitting ? "登録中..." : "登録する"}
          </button>
        </div>
      </form>
    </div>
  );
}
