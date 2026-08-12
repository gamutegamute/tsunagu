import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import HistoryListItem from "../components/history/HistoryListItem.jsx";
import { useShelterList } from "../hooks/useShelterList.js";
import { getSentReportHistory } from "../utils/sentReportHistory.js";
import { getPendingReports } from "../utils/pendingReports.js";
import { mergeHistoryEntries } from "../utils/historyEntries.js";
import { loadJson } from "../utils/localJson.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

function formatTime(observedAtIso) {
  return new Date(observedAtIso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

/**
 * モバイル向け送信履歴画面(/history、決定事項22)。
 * 「この端末が」実際にサーバーへ送信できた報告(sentReportHistory)に加え、
 * まだ送信できていない保留中の報告(pendingReports)もマージして表示する
 * (全避難所横断のTimelineは本部PC側のみに実装する方針のため、ここには含めない)。
 *
 * 決定事項33-a: Field Report・Dashboard等、他画面と統一感のあるデザインに改善
 * (panel + section-title の共通レイアウトを採用し、一覧はカード形式にした)。
 *
 * ページ表示時に1回読むだけの静的スナップショットとし、自動更新は行わない
 * (バックグラウンドで保留報告が再送・成功した場合は、この画面を開き直すと反映される)。
 */
export default function HistoryPage() {
  const navigate = useNavigate();
  const shelters = useShelterList();
  const [pendingReports, setPendingReports] = useState(() => loadJson(STORAGE_KEYS.pendingReports, []));
  const history = mergeHistoryEntries(getSentReportHistory(), pendingReports);

  useEffect(() => {
    let isCurrent = true;
    void getPendingReports().then((reports) => {
      if (isCurrent) setPendingReports(reports);
    });
    return () => {
      isCurrent = false;
    };
  }, []);

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
        <section className="panel history-panel">
          <div className="section-title">
            <h2>この端末からの送信履歴</h2>
            <span className="history-count-badge">{history.length}件</span>
          </div>

          <div className="history-list">
            {history.length === 0 ? (
              <p className="incident-empty-state">送信履歴はまだありません</p>
            ) : (
              history.map((entry) => (
                <HistoryListItem
                  key={entry.key}
                  time={formatTime(entry.observedAt)}
                  shelterLabel={shelterLabel(entry.shelterId)}
                  urgency={entry.urgency}
                  status={entry.status}
                />
              ))
            )}
          </div>
        </section>
      </main>
    </>
  );
}
