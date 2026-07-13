/**
 * 水の不足予測(決定事項10): 「現在の水量 ÷ 1日あたりの消費量」の単純計算。
 * 人数の予測は行わない(決定事項10)。
 */
export function computeWaterShortageForecast(historyPoints) {
  if (historyPoints.length < 2) return null;

  const first = historyPoints[0];
  const latest = historyPoints[historyPoints.length - 1];
  const elapsedDays = (new Date(latest.observedAt) - new Date(first.observedAt)) / (1000 * 60 * 60 * 24);
  if (elapsedDays <= 0) return null;

  const consumed = first.waterStock - latest.waterStock;
  if (consumed <= 0) return null; // 減っていなければ不足予測はしない

  const dailyConsumption = consumed / elapsedDays;
  const daysUntilShortage = latest.waterStock / dailyConsumption;

  return {
    dailyConsumption: Math.round(dailyConsumption),
    daysUntilShortage: Math.max(0, Math.round(daysUntilShortage)),
    currentWaterStock: latest.waterStock,
  };
}
