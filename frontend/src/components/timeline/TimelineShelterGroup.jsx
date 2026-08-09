import { useState } from "react";
import TimelineRow from "./TimelineRow.jsx";
import { fetchShelterObservations } from "../../api.js";

/**
 * Timeline1避難所分のグループ(アコーディオン形式)。
 *
 * 常に最新の報告を1件表示し、「▼ 過去の報告を見る」を押すと
 * GET /api/shelters/{id}/observations を呼んで、その避難所の過去の報告を
 * observed_at降順で追加表示する。初回展開時のみ取得し、以降はキャッシュを使い回す。
 */
export default function TimelineShelterGroup({ shelter, latestObservation }) {
  const [expanded, setExpanded] = useState(false);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleToggle() {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    if (!nextExpanded || history !== null) return;

    setLoading(true);
    setError(null);
    try {
      const items = await fetchShelterObservations(shelter.id);
      setHistory(items);
    } catch {
      setError("過去の報告履歴の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  const pastEntries = (history || []).filter((observation) => observation.id !== latestObservation.id);

  return (
    <div className="timeline-shelter-group">
      <TimelineRow
        observedAt={latestObservation.observed_at}
        shelter={shelter}
        reporterName={latestObservation.reporter_name}
        urgency={latestObservation.urgency}
        summary={latestObservation.memo}
        source={latestObservation.source}
      />

      <button
        type="button"
        className="text-link-button timeline-history-toggle"
        onClick={handleToggle}
        aria-expanded={expanded}
      >
        {expanded ? "▲ 過去の報告を閉じる" : "▼ 過去の報告を見る"}
      </button>

      {expanded && (
        <div className="timeline-history-panel">
          {loading && <p className="timeline-history-status">読み込み中…</p>}
          {error && <p className="timeline-history-status timeline-history-error">{error}</p>}
          {!loading && !error && pastEntries.length === 0 && (
            <p className="timeline-history-status">過去の報告はありません</p>
          )}
          {!loading && !error && pastEntries.map((observation) => (
            <TimelineRow
              key={observation.id}
              observedAt={observation.observed_at}
              shelter={shelter}
              reporterName={observation.reporter_name}
              urgency={observation.urgency}
              summary={observation.memo}
              source={observation.source}
            />
          ))}
        </div>
      )}
    </div>
  );
}
