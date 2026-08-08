/**
 * バックエンドのGET /api/incidents(決定事項34-a/34-b)が返す1件を、画面側で
 * 扱いやすいキャメルケースの形に正規化する。
 *
 * 決定事項1: Incidentは現場報告のメモ欄をインシデント欄として扱う。以前は
 * GET /api/dashboard(避難所ごとの最新1件のみ)からメモ入りの報告を抽出し、
 * 確認/対応状態はこの端末のlocalStorage(incidentStore.js)から合成していたが、
 * この方式では新しい報告が来た瞬間に古いIncidentが一覧から消える問題があった
 * (決定事項34-a)。GET /api/incidentsはメモ入りの全observationsをサーバー側で
 * 絞り込んで返し、状態(incident_states)もサーバーで一元管理されるため、
 * この問題と複数PC間での状態非共有(決定事項34-b)の両方を解消する。
 * ここでは単にフィールド名をキャメルケースへ揃えるだけになっている。
 */
export function normalizeIncident(incident) {
  const state = incident.state;
  return {
    id: incident.id,
    shelter: incident.shelter,
    urgency: incident.urgency,
    memo: incident.memo,
    observedAt: incident.observed_at,
    confirmStatus: state.confirm_status,
    confirmedBy: state.confirmed_by,
    confirmMemo: state.confirm_memo,
    resolutionRequest: state.resolution_request_at
      ? {
          memo: state.resolution_request_memo,
          staffName: state.resolution_request_staff_name,
          targetShelterId: incident.shelter.id,
          activeShelterId: state.resolution_request_active_shelter_id,
          requestedAt: state.resolution_request_at,
        }
      : null,
    resolution: state.resolution_approved_at
      ? {
          memo: state.resolution_memo,
          staffName: state.resolution_staff_name,
          approverName: state.resolution_approver_name,
          approvedAt: state.resolution_approved_at,
        }
      : null,
  };
}

/** 対応済み(承認確定)かどうか。 */
export function isResolved(incident) {
  return Boolean(incident.resolution);
}

/** 本部の承認待ち(モバイルから申請済み・未承認)かどうか。 */
export function isPendingApproval(incident) {
  return Boolean(incident.resolutionRequest) && !incident.resolution;
}

/** 現場から対応済み申請を送れる状態かどうか。確認済みでも未解決なら申請できる。 */
export function canRequestResolution(incident) {
  return !isResolved(incident) && !isPendingApproval(incident);
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
