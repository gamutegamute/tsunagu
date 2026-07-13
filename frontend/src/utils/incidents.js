import { getIncidentState } from "./incidentStore.js";

/**
 * 避難所ステータス一覧(GET /api/dashboard相当)から「インシデント」を抽出する。
 *
 * 決定事項1: Incidentは現場報告のメモ欄をインシデント欄として扱う。
 * バックエンドは「避難所ごとの最新の報告」しか返さない(履歴APIが無い)ため、
 * 各避難所の最新報告にメモが入っていれば、それを1件のIncidentとみなす
 * (新しい報告が来るとメモが空でも古いIncidentは一覧から消える暫定挙動。
 *  詳細は申し送り事項を参照)。
 */
export function deriveIncidentsFromDashboard(shelterStatusList) {
  return shelterStatusList
    .filter((item) => item.latest_observation && item.latest_observation.memo && item.latest_observation.memo.trim())
    .map((item) => {
      const observation = item.latest_observation;
      const localState = getIncidentState(observation.id);
      return {
        id: observation.id,
        shelter: item.shelter,
        urgency: item.status,
        memo: observation.memo,
        observedAt: observation.observed_at,
        ...localState,
      };
    });
}

/** 対応済み(承認確定)かどうか。 */
export function isResolved(incident) {
  return Boolean(incident.resolution);
}

/** 本部の承認待ち(モバイルから申請済み・未承認)かどうか。 */
export function isPendingApproval(incident) {
  return Boolean(incident.resolutionRequest) && !incident.resolution;
}

function formatDateTime(iso) {
  return new Date(iso).toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * IncidentCardの表示用に、担当者タグ・状態メッセージ・対応済み情報を組み立てる。
 * モバイル/PCどちらのカードでも同じ表示ロジックを使うための共通ヘルパー。
 */
export function describeIncidentDisplay(incident) {
  if (isResolved(incident)) {
    return {
      assigneeLabel: incident.resolution.staffName || null,
      statusNote: null,
      resolutionInfo: incident.resolution,
    };
  }
  if (isPendingApproval(incident)) {
    return {
      assigneeLabel: null,
      statusNote: `対応済み申請: ${incident.resolutionRequest.staffName}・${formatDateTime(incident.resolutionRequest.requestedAt)}(本部承認待ち)`,
      resolutionInfo: null,
    };
  }
  if (incident.confirmStatus === "CONFIRMED") {
    return {
      assigneeLabel: incident.confirmedBy ? `担当: ${incident.confirmedBy}` : null,
      statusNote: incident.confirmMemo ? `確認メモ: ${incident.confirmMemo}` : null,
      resolutionInfo: null,
    };
  }
  return { assigneeLabel: null, statusNote: null, resolutionInfo: null };
}
