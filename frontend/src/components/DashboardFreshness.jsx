export default function DashboardFreshness({ error, isCached, lastSuccessAt }) {
  if (isCached === undefined && !error && !lastSuccessAt) return null;
  return <aside role={error ? "alert" : "status"}>
    {error && <p>{error}</p>}
    <p>{isCached ? "保持データを表示中。最新情報とは限りません。" : "最新の取得結果を表示中。"}
      {` 最終取得成功: ${lastSuccessAt ? new Date(lastSuccessAt).toLocaleString("ja-JP") : "不明"}`}</p>
  </aside>;
}
