import { useNavigate } from "react-router-dom";
import HistoryListItem from "../components/history/HistoryListItem.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { getSentReportHistory } from "../utils/sentReportHistory.js";

function formatTime(observedAtIso) {
  return new Date(observedAtIso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

/**
 * モバイル向け送信履歴画面(/history、決定事項22)。
 * 「この端末が」実際にサーバーへ送信できた報告だけを表示する簡易リスト
 * (全避難所横断のTimelineは本部PC側のみに実装する方針のため、ここには含めない)。
 */
export default function HistoryPage() {
  const navigate = useNavigate();
  const shelters = useShelterList();
  const history = getSentReportHistory();

  function shelterLabel(shelterId) {
    const shelter = shelters.find((item) => item.id === shelterId);
    return shelter ? `${shelter.id} ${shelter.name}` : shelterId;
  }

  return (
    <>
      <header className="topbar incident-header">
        <div className="incident-header-title-row">
          <button type="button" className="icon-nav-button" onClick={() => navigate(-1)} aria-label="戻る">
            ←
          </button>
          <h1>送信履歴</h1>
        </div>
      </header>

      <main className="layout-mobile">
        <div className="history-list">
          {history.length === 0 && <p className="incident-empty-state">送信履歴はまだありません</p>}
          {history.map((entry, index) => (
            <HistoryListItem
              key={`${entry.sentAt}-${index}`}
              time={formatTime(entry.observedAt)}
              shelterLabel={shelterLabel(entry.shelterId)}
              urgency={entry.urgency}
            />
          ))}
        </div>
      </main>
    </>
  );
}
