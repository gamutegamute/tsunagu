// localStorage に保存するときのキー名を1か所にまとめたもの。
// キー名を各ファイルに直接書くと、タイプミスで「保存したつもりが読み込めない」
// バグに気づきにくくなるため、ここでしか定義しない。
const KEY_SUFFIXES = {
  pendingReports: "pendingReports",
  cachedDashboard: "cachedDashboard",
  reporterName: "reporterName",
  approverName: "approverName",
  activeShelter: "activeShelter",
  sentReportHistory: "sentReportHistory",
  incidentStates: "incidentStates",
  shelterCapacities: "shelterCapacities",
  shelterObservationHistory: "shelterObservationHistory",
};

export const STORAGE_KEYS = Object.fromEntries(
  Object.entries(KEY_SUFFIXES).map(([name, suffix]) => [name, `tsunagu.${suffix}`]),
);

// 改名前の端末に残る未送信データや設定を、新しいキーへ一度だけ引き継ぐ。
try {
  for (const [name, suffix] of Object.entries(KEY_SUFFIXES)) {
    const newKey = STORAGE_KEYS[name];
    const legacyValue = localStorage.getItem(`shelteros.${suffix}`);
    if (localStorage.getItem(newKey) === null && legacyValue !== null) {
      localStorage.setItem(newKey, legacyValue);
    }
  }
} catch {
  // localStorageを使用できないブラウザでもアプリ自体は起動させる。
}
