function formatAxisDate(iso) {
  return new Date(iso).toLocaleDateString("ja-JP", { month: "numeric", day: "numeric" });
}

/**
 * 避難者数の推移グラフ(決定事項10: 人数は予測せず推移表示のみ)。
 * キャパシティは決定事項9・13の値を横線で重ねて表示する。
 */
export default function PeopleTrendChart({ history, capacity }) {
  if (history.length < 2) {
    return (
      <div className="chart-card">
        <p className="chart-card-title">避難者数の推移(人)</p>
        <p className="chart-empty-state">
          データを収集中です。本部PCでダッシュボードの表示・再読み込みを重ねると、この端末に推移データが蓄積されて表示されます。
        </p>
      </div>
    );
  }

  const latest = history[history.length - 1];
  const maxValue = Math.max(...history.map((point) => point.peopleCount), capacity || 0, 1);
  const capacityRatioPercent = capacity ? Math.min(100, Math.round((capacity / maxValue) * 100)) : null;
  const occupancyRate = capacity ? Math.round((latest.peopleCount / capacity) * 100) : null;

  return (
    <div className="chart-card">
      <div className="chart-card-title-row">
        <p className="chart-card-title">避難者数の推移(人)</p>
        <p className="chart-card-title-note">推移の表示のみ(予測は行いません)</p>
      </div>

      <div className="chart-area">
        <div className="chart-y-axis">
          <span>{maxValue}人</span>
          <span>{Math.round(maxValue / 2)}人</span>
          <span>0人</span>
        </div>
        <div className="chart-body">
          <div className="chart-bars chart-bars-with-capacity-line">
            {capacityRatioPercent !== null && (
              <>
                <div className="capacity-line" style={{ bottom: `${capacityRatioPercent}%` }} />
                <span className="capacity-label" style={{ bottom: `${capacityRatioPercent}%` }}>
                  キャパ {capacity}人
                </span>
              </>
            )}
            {history.map((point, index) => (
              <div
                key={index}
                className="chart-bar chart-bar-people"
                style={{ height: `${(point.peopleCount / maxValue) * 100}%` }}
                title={`${formatAxisDate(point.observedAt)}: ${point.peopleCount}人`}
              />
            ))}
          </div>
          <div className="chart-x-axis">
            <span>{formatAxisDate(history[0].observedAt)}</span>
            <span>{formatAxisDate(latest.observedAt)}(今日)</span>
          </div>
        </div>
      </div>

      <p className="chart-note">
        現在 {latest.peopleCount}人{capacity ? ` / キャパシティ ${capacity}人(充足率 ${occupancyRate}%)` : "(キャパシティ未設定)"}
      </p>
    </div>
  );
}
