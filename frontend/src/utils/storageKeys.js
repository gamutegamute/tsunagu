// localStorage に保存するときのキー名を1か所にまとめたもの。
// キー名を各ファイルに直接書くと、タイプミスで「保存したつもりが読み込めない」
// バグに気づきにくくなるため、ここでしか定義しない。
export const STORAGE_KEYS = {
  pendingReports: "shelteros.pendingReports",
  cachedDashboard: "shelteros.cachedDashboard",
  reporterName: "shelteros.reporterName",
  approverName: "shelteros.approverName",
  activeShelter: "shelteros.activeShelter",
  sentReportHistory: "shelteros.sentReportHistory",
  incidentStates: "shelteros.incidentStates",
  shelterCapacities: "shelteros.shelterCapacities",
  shelterObservationHistory: "shelteros.shelterObservationHistory",
};
