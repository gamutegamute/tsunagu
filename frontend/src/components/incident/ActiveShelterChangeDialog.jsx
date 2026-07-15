/**
 * 「アクティブ避難所」を選び直したときの確認ダイアログ(決定事項23の3)。
 * 誤操作防止が目的のため、変更内容(どこからどこへ)を明示する。
 */
export default function ActiveShelterChangeDialog({ fromShelterLabel, toShelterLabel, onCancel, onConfirm }) {
  return (
    <div className="modal-overlay modal-overlay-center" role="dialog" aria-modal="true">
      <div className="confirm-dialog-card">
        <p className="confirm-dialog-title">アクティブ避難所を変更しますか?</p>
        <p className="confirm-dialog-body">
          アクティブ避難所を「{fromShelterLabel}」から「{toShelterLabel}」に変更します。次回以降、この端末での報告・申請時のデフォルト選択も更新されます。
        </p>
        <div className="confirm-dialog-footer">
          <button type="button" className="secondary-button" onClick={onCancel}>
            キャンセル
          </button>
          <button type="button" className="primary-button" onClick={onConfirm}>
            変更する
          </button>
        </div>
      </div>
    </div>
  );
}
