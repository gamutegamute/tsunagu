import { computeWaterShortageForecast } from "../../utils/forecast.js";

function formatAxisDate(iso) {
  return new Date(iso).toLocaleDateString("ja-JP", { month: "numeric", day: "numeric" });
}

/**
 * 水在庫の推移・予測グラフ(決定事項10、Figma: ChartCard/水の推移・予測)。
 * バックエンドに履歴APIが無いため、この端末で蓄積したローカルの簡易履歴を使う
 * (utils/shelterObservationHistory.js。詳細は申し送り事項を参照)。
 */
export default function WaterTrendChart({ history }) {
  if (history.length < 2) {
    return (
      <div className="chart-card">
        <p className="chart-card-title">水在庫の推移(L)</p>
        <p className="chart-empty-state">
          データを収集中です。本部PCでダッシュボードの表示・再読み込みを重ねると、この端末に推移データが蓄積されて表示されます。
        </p>
      </div>
    );
  }

  const forecast = computeWaterShortageForecast(history);
  const latest = history[history.length - 1];

  const forecastBars = forecast
    ? [1, 2].map((step) => ({
        label: "予測",
        value: Math.max(0, Math.round(latest.waterStock - forecast.dailyConsumption * step)),
        isForecast: true,
      }))
    : [];

  const actualBars = history.map((point) => ({
    label: formatAxisDate(point.observedAt),
    value: point.waterStock,
    isForecast: false,
  }));

  const allBars = [...actualBars, ...forecastBars];
  const maxValue = Math.max(...allBars.map((bar) => bar.value), 1);

  return (
    <div className="chart-card">
      <div className="chart-card-title-row">
        <p className="chart-card-title">水在庫の推移(L)</p>
        {forecastBars.length > 0 && (
          <div className="chart-legend">
            <span className="chart-legend-item">
              <span className="chart-legend-swatch chart-legend-swatch-actual" />
              実績
            </span>
            <span className="chart-legend-item">
              <span className="chart-legend-swatch chart-legend-swatch-forecast" />
              予測
            </span>
          </div>
        )}
      </div>

      <div className="chart-area">
        <div className="chart-y-axis">
          <span>{maxValue}L</span>
          <span>{Math.round(maxValue / 2)}L</span>
          <span>0L</span>
        </div>
        <div className="chart-body">
          <div className="chart-bars">
            {allBars.map((bar, index) => (
              <div
                key={index}
                className={`chart-bar ${bar.isForecast ? "chart-bar-forecast" : "chart-bar-actual"}`}
                style={{ height: `${(bar.value / maxValue) * 100}%` }}
                title={`${bar.label}: ${bar.value}L${bar.isForecast ? "(予測)" : ""}`}
              />
            ))}
          </div>
          <div className="chart-x-axis">
            <span>{actualBars[0].label}</span>
            <span>{actualBars[actualBars.length - 1].label}(今日)</span>
          </div>
        </div>
      </div>

      {forecast ? (
        <div className="shortage-alert">
          <span className="shortage-alert-icon">!</span>
          <div>
            <p className="shortage-alert-title">約{forecast.daysUntilShortage}日で水が不足する見込み</p>
            <p className="shortage-alert-detail">
              現在{forecast.currentWaterStock}L ÷ 1日あたり消費 約{forecast.dailyConsumption}L で算出
            </p>
          </div>
        </div>
      ) : (
        <p className="chart-note">水位は増加・横ばい傾向のため、不足予測は表示していません。</p>
      )}
    </div>
  );
}
