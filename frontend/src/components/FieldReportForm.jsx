import { useEffect, useRef, useState } from "react";
import { createClientEventId } from "../utils/clientEventId.js";
import StatusHeroBanner from "./StatusHeroBanner.jsx";
import ReporterNameField from "./fields/ReporterNameField.jsx";
import ShelterSelectField from "./fields/ShelterSelectField.jsx";
import PeopleAndWaterFields from "./fields/PeopleAndWaterFields.jsx";
import UrgencyField from "./fields/UrgencyField.jsx";
import MemoField from "./fields/MemoField.jsx";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

/**
 * 現場からの状況報告フォーム。
 *
 * 人数・水・緊急度・メモ・報告者名・避難所はすべてこのコンポーネントの中だけで
 * 状態管理する。送信時にまとめて onSubmitReport に渡し、実際のAPI呼び出しや
 * オフラインキューへの退避などは親(FieldReportPage)に任せる
 * (このコンポーネントは「フォームの入力・送信」にだけ責任を持つ)。
 *
 * 通信状態(networkMode/offlinePhase)はすべて自動判定(useNetworkMode、決定事項27・29)
 * であり、このフォーム自身には手動切り替えの手段を持たせない。実際のLoRa送信は
 * T-Beam専用ページ(決定事項28・29)が担当するため、ここには送信処理を持たせない。
 */
export default function FieldReportForm({
  shelters,
  networkMode,
  offlinePhase,
  pendingReportCount,
  isSyncing,
  onSyncPendingReports,
  onSubmitReport,
}) {
  const [reporterName, setReporterName] = useState(() => localStorage.getItem(STORAGE_KEYS.reporterName) || "");
  const [shelterId, setShelterId] = useState("");
  const [peopleCount, setPeopleCount] = useState(50);
  const [waterStock, setWaterStock] = useState(20);
  const [urgency, setUrgency] = useState("NORMAL");
  const [memo, setMemo] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState("");
  const [submitError, setSubmitError] = useState("");
  const submitting = useRef(false);
  const lastAttempt = useRef(null);

  // 避難所一覧が届いたタイミングで、まだ何も選ばれていなければ先頭の避難所を選んでおく
  useEffect(() => {
    if (!shelterId && shelters.length > 0) {
      setShelterId(shelters[0].id);
    }
  }, [shelters, shelterId]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (submitting.current) return;
    const fields = {
      reporterName,
      shelterId,
      peopleCount: Number(peopleCount),
      waterStock: Number(waterStock),
      urgency,
      memo,
    };
    const fingerprint = JSON.stringify(fields);
    if (lastAttempt.current?.fingerprint !== fingerprint) {
      lastAttempt.current = { fingerprint, clientEventId: createClientEventId(), observedAt: new Date().toISOString() };
    }
    submitting.current = true;
    setIsSubmitting(true);
    setSubmitMessage("");
    setSubmitError("");
    try {
      const result = await onSubmitReport({ ...fields, ...lastAttempt.current });
      setMemo("");
      lastAttempt.current = null;
      setSubmitMessage(result === "queued" ? "端末に保存しました。接続後に再送します。" : "報告を送信しました。");
    } catch (error) {
      setSubmitError(`送信・保存できませんでした。入力を保持しています。${error.message || "再試行してください。"}`);
    } finally {
      submitting.current = false;
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel report-panel">
      <div className="section-title">
        <h2>現場報告</h2>
        <span className={`network ${networkMode}`}>{networkMode === "offline" ? "オフライン" : "オンライン"}</span>
      </div>

      <StatusHeroBanner networkMode={networkMode} offlinePhase={offlinePhase} />

      <form onSubmit={handleSubmit}>
        <fieldset disabled={isSubmitting} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <ReporterNameField reporterName={reporterName} onChange={setReporterName} />
        <ShelterSelectField shelters={shelters} selectedShelterId={shelterId} onChange={setShelterId} />
        <PeopleAndWaterFields
          peopleCount={peopleCount}
          waterStock={waterStock}
          onPeopleCountChange={setPeopleCount}
          onWaterStockChange={setWaterStock}
        />
        <UrgencyField urgency={urgency} onChange={setUrgency} />
        <MemoField memo={memo} onChange={setMemo} />
        {pendingReportCount > 0 && (
          <button
            className="sync-pending-reports"
            type="button"
            onClick={() => void onSyncPendingReports()}
            disabled={networkMode !== "normal" || isSyncing}
          >
            {isSyncing ? "同期中..." : "未送信データを同期"}
          </button>
        )}
        <p className="pending">未送信 {pendingReportCount}件</p>
        <button type="submit" disabled={isSubmitting}>{isSubmitting ? "保存・送信中..." : "報告する"}</button>
        </fieldset>
        {submitError && <p role="alert">{submitError}</p>}
        {submitMessage && <p role="status">{submitMessage}</p>}
      </form>
    </section>
  );
}
