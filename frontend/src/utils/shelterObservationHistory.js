import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

const MAX_POINTS_PER_SHELTER = 30;

/**
 * 避難所ごとの「推移・予測」グラフ(決定事項10・16)用の簡易時系列データ。
 *
 * バックエンドには避難所ごとの履歴を返すAPIが無く、常に最新の1件しか
 * 取得できない(申し送り事項を参照)。そのためこのPCがダッシュボードを
 * 読み込むたびに、その時点の最新値をこの端末のlocalStorageへ1点ずつ
 * 積み上げて簡易的な推移データとして使う(この端末で観測した分のみ・
 * ページを開いていない間の変化は記録されない暫定実装)。
 */
function readAll() {
  return loadJson(STORAGE_KEYS.shelterObservationHistory, {});
}

function writeAll(all) {
  localStorage.setItem(STORAGE_KEYS.shelterObservationHistory, JSON.stringify(all));
}

/** dashboardItems(GET /api/dashboard相当)を1回ぶん記録する。 */
export function recordDashboardSnapshot(shelterStatusList) {
  const all = readAll();
  for (const item of shelterStatusList) {
    const observation = item.latest_observation;
    if (!observation) continue;

    const points = all[item.shelter.id] || [];
    const alreadyRecorded = points.some((point) => point.observedAt === observation.observed_at);
    if (alreadyRecorded) continue;

    const nextPoints = [
      ...points,
      { observedAt: observation.observed_at, peopleCount: observation.people_count, waterStock: observation.water_stock },
    ]
      .sort((a, b) => new Date(a.observedAt) - new Date(b.observedAt))
      .slice(-MAX_POINTS_PER_SHELTER);

    all[item.shelter.id] = nextPoints;
  }
  writeAll(all);
}

export function getHistory(shelterId) {
  return readAll()[shelterId] || [];
}
