import {
  confirmIncident as confirmIncidentApi,
  resolveIncident as resolveIncidentApi,
  requestIncidentResolution as requestIncidentResolutionApi,
  approveIncidentResolutionRequest as approveIncidentResolutionRequestApi,
} from "../api.js";

/**
 * Incidentの状態(未確認/確認済み/対応済み申請/対応済み確定)を更新するための
 * 呼び出し口。
 *
 * 決定事項34-a/34-bにより、これらの状態はもうこの端末のlocalStorageだけでは
 * 完結せず、バックエンドのincident_statesテーブルへ永続化される(本部PCが
 * 複数あっても状態が共有される)。呼び出し元(IncidentPage.jsx・
 * PcIncidentCard.jsx等)からの呼び出しインターフェース(関数名・引数の形)は
 * 変えずに済むよう、ここはAPI呼び出しへの薄いラッパーとして残している。
 *
 * 呼び出し後は、画面側で最新状態を反映するためuseIncidents()のrefresh()を
 * 呼ぶこと(このファイル自体はローカル状態を持たない)。
 */

/**
 * モバイルからの「対応済みにする」申請(決定事項12・23)。
 * 本部の承認が下りるまでは resolution は確定しない。
 *
 * targetShelterIdは、対象のIncidentが属する避難所そのもの(observation_id経由
 * でサーバー側から常に一意に分かる)なので、送信データには含めない。
 */
export async function requestResolution(incidentId, { memo, staffName, activeShelterId }) {
  return requestIncidentResolutionApi(incidentId, { staffName, memo, activeShelterId });
}

/** PC(本部)専用の「確認済みにする」(決定事項14)。 */
export async function confirmIncident(incidentId, { approverName, memo }) {
  return confirmIncidentApi(incidentId, { approverName, memo });
}

/**
 * PC(本部)が申請を経由せず直接「対応済みにする」場合(決定事項14: PC専用操作)。
 * 承認者本人がその場で対応内容を記録するため、承認待ちを経由せず即確定する。
 */
export async function resolveIncidentDirectly(incidentId, { approverName, memo, staffName }) {
  return resolveIncidentApi(incidentId, { approverName, staffName, memo });
}

/** モバイルからの申請を、PC(本部)が承認して確定する(決定事項2・7・12)。 */
export async function approveResolutionRequest(incidentId, { approverName }) {
  return approveIncidentResolutionRequestApi(incidentId, { approverName });
}
