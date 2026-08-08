import { useCallback, useEffect, useState } from "react";
import { fetchIncidents } from "../api.js";
import { normalizeIncident } from "../utils/incidents.js";

/**
 * 全避難所のインシデント一覧を取得するフック(決定事項2: 閲覧は全エリア可)。
 *
 * 決定事項34-a/34-bにより、GET /api/incidentsから直接取得する形に変更した。
 * 以前はGET /api/dashboard(避難所ごとの最新1件のみ)からメモ入りの報告を
 * 抽出し、確認/対応状態はこの端末のlocalStorageから合成していたが、この方式
 * では新しい報告が来た瞬間に古いIncidentが一覧から消える問題があった
 * (決定事項34-a)。GET /api/incidentsは絞り込まず全件返し、状態も
 * サーバー側(incident_states)で一元管理されるため、この問題と複数PC間での
 * 状態非共有(決定事項34-b)の両方を解消する。
 */
export function useIncidents() {
  const [incidents, setIncidents] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const rawIncidents = await fetchIncidents();
      setIncidents(rawIncidents.map(normalizeIncident));
    } catch (error) {
      console.error(error);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { incidents, refresh };
}
