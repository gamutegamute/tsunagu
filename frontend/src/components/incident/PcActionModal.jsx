import { useState } from "react";

/**
 * PC(本部)側の「確認済みにする」「対応済みにする」操作用の簡易モーダル(決定事項12)。
 * 担当者はログイン中の承認者名を自動で使うため、入力するのはメモのみ。
 */
export default function PcActionModal({ title, subtitle, confirmLabel, onCancel, onSubmit }) {
  const [memo, setMemo] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    const trimmedMemo = memo.trim();
    if (!trimmedMemo) return;
    onSubmit(trimmedMemo);
  }

  return (
    <div className="modal-overlay modal-overlay-center" role="dialog" aria-modal="true">
      <form className="confirm-dialog-card pc-action-modal" onSubmit={handleSubmit}>
        <p className="confirm-dialog-title">{title}</p>
        {subtitle && <p className="confirm-dialog-body">{subtitle}</p>}
        <label className="bottom-sheet-field">
          メモ(必須)
          <textarea
            rows={3}
            placeholder="対応内容を記入してください"
            value={memo}
            onChange={(event) => setMemo(event.target.value)}
            required
          />
        </label>
        <div className="confirm-dialog-footer">
          <button type="button" className="secondary-button" onClick={onCancel}>
            キャンセル
          </button>
          <button type="submit" className="primary-button">
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
