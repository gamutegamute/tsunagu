import { useState } from "react";
import ActiveShelterChangeDialog from "./ActiveShelterChangeDialog.jsx";
import { getActiveShelter, setActiveShelter } from "../../utils/activeShelter.js";
import { STORAGE_KEYS } from "../../utils/storageKeys.js";

function shelterLabel(shelters, shelterId) {
  const shelter = shelters.find((item) => item.id === shelterId);
  return shelter ? `${shelter.id} ${shelter.name}` : shelterId;
}

/**
 * モバイルの「対応済みにする」申請フォーム(決定事項12・23、Figma: Incident/対応確定モーダル)。
 *
 * - メモ・担当者は必須(決定事項12)
 * - アクティブ避難所は直近報告した避難所をデフォルト選択し、選び直すと確認ダイアログを挟む(決定事項23)
 * - 送信はあくまで「申請」までで、確定(対応済み)は本部(PC)の承認を待つ(決定事項2・14)
 */
export default function ResolutionRequestModal({ incident, shelters, onCancel, onSubmit }) {
  const lastStaffName = localStorage.getItem(STORAGE_KEYS.reporterName) || "";
  const [memo, setMemo] = useState("");
  const [staffName, setStaffName] = useState(lastStaffName);
  const [previousActiveShelterId] = useState(() => getActiveShelter() || incident.shelter.id);
  const [activeShelterId, setActiveShelterId] = useState(previousActiveShelterId);
  const [pendingShelterId, setPendingShelterId] = useState(null);

  function handleShelterSelectChange(event) {
    const newShelterId = event.target.value;
    if (newShelterId === activeShelterId) return;
    setPendingShelterId(newShelterId);
  }

  function confirmShelterChange() {
    setActiveShelter(pendingShelterId);
    setActiveShelterId(pendingShelterId);
    setPendingShelterId(null);
  }

  function handleSubmit(event) {
    event.preventDefault();
    const trimmedMemo = memo.trim();
    const trimmedStaffName = staffName.trim();
    if (!trimmedMemo || !trimmedStaffName) return;

    if (trimmedStaffName) {
      localStorage.setItem(STORAGE_KEYS.reporterName, trimmedStaffName);
    }

    onSubmit({
      memo: trimmedMemo,
      staffName: trimmedStaffName,
      targetShelterId: incident.shelter.id,
      activeShelterId,
    });
  }

  return (
    <div className="modal-overlay modal-overlay-bottom" role="dialog" aria-modal="true">
      <form className="bottom-sheet" onSubmit={handleSubmit}>
        <div className="bottom-sheet-titles">
          <p className="bottom-sheet-title">対応済みにする</p>
          <p className="bottom-sheet-subtitle">
            対象: {incident.shelter.id} {incident.shelter.name} — {incident.memo}
          </p>
        </div>

        <label className="bottom-sheet-field">
          アクティブ避難所(必須)
          <div className="bottom-sheet-select-row">
            <select value={activeShelterId} onChange={handleShelterSelectChange}>
              {shelters.map((shelter) => (
                <option key={shelter.id} value={shelter.id}>
                  {shelter.id} {shelter.name}
                </option>
              ))}
            </select>
            <span className="assignee-tag">
              <span className="assignee-tag-dot" />
              前回: {previousActiveShelterId}
            </span>
          </div>
          <span className="bottom-sheet-hint">別の避難所を選び直すと確認ダイアログが表示されます</span>
        </label>

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

        <label className="bottom-sheet-field">
          担当者(必須)
          <input
            type="text"
            placeholder="田中"
            value={staffName}
            onChange={(event) => setStaffName(event.target.value)}
            required
          />
          {lastStaffName && (
            <span className="bottom-sheet-recall-row">
              <span className="assignee-tag">
                <span className="assignee-tag-dot" />
                前回: {lastStaffName}
              </span>
              <button type="button" className="text-link-button" onClick={() => setStaffName(lastStaffName)}>
                タップで入力(端末に保存された前回の名前)
              </button>
            </span>
          )}
        </label>

        <p className="bottom-sheet-note">
          ※ モバイルからは申請までとなり、本部(PC)の承認後に対応済みが確定します。担当エリア外は閲覧のみ可能です。
        </p>

        <div className="bottom-sheet-footer">
          <button type="button" className="secondary-button" onClick={onCancel}>
            キャンセル
          </button>
          <button type="submit" className="primary-button">
            対応済みを申請する
          </button>
        </div>
      </form>

      {pendingShelterId && (
        <ActiveShelterChangeDialog
          fromShelterLabel={shelterLabel(shelters, activeShelterId)}
          toShelterLabel={shelterLabel(shelters, pendingShelterId)}
          onCancel={() => setPendingShelterId(null)}
          onConfirm={confirmShelterChange}
        />
      )}
    </div>
  );
}
