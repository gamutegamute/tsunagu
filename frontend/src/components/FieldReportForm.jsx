import { useEffect, useState } from "react";
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
export default function FieldReportForm({ shelters, networkMode, offlinePhase, pendingReportCount, onSubmitReport }) {
  const [reporterName, setReporterName] = useState(() => localStorage.getItem(STORAGE_KEYS.reporterName) || "");
  const [shelterId, setShelterId] = useState("");
  const [peopleCount, setPeopleCount] = useState(50);
  const [waterStock, setWaterStock] = useState(20);
  const [urgency, setUrgency] = useState("NORMAL");
  const [memo, setMemo] = useState("");

  // 避難所一覧が届いたタイミングで、まだ何も選ばれていなければ先頭の避難所を選んでおく
  useEffect(() => {
    if (!shelterId && shelters.length > 0) {
      setShelterId(shelters[0].id);
    }
  }, [shelters, shelterId]);

  function handleSubmit(event) {
    event.preventDefault();
    onSubmitReport({
      reporterName,
      shelterId,
      peopleCount: Number(peopleCount),
      waterStock: Number(waterStock),
      urgency,
      memo,
    });
    setMemo(""); // 送信後はメモ欄だけ空にする(他の項目は次回報告でも使い回せるよう残す)
  }

  return (
    <section className="panel report-panel">
      <div className="section-title">
        <h2>現場報告</h2>
        <span className={`network ${networkMode}`}>{networkMode === "offline" ? "オフライン" : "オンライン"}</span>
      </div>

      <StatusHeroBanner networkMode={networkMode} offlinePhase={offlinePhase} />

      <form onSubmit={handleSubmit}>
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
        <p className="pending">未送信 {pendingReportCount}件</p>
        <button type="submit">報告する</button>
      </form>
    </section>
  );
}
