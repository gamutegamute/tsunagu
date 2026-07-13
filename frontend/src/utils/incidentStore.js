import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

/**
 * Incidentの状態(未確認/確認済み/対応済み申請/対応済み確定)を保存する層。
 *
 * バックエンドにIncident専用のテーブル・APIがまだ存在しない(2026/07時点)ため、
 * 「フロント先行で実装し、必要なAPI仕様は申し送りする」方針に基づき、
 * この端末のlocalStorageだけで状態を完結させる暫定実装にしている。
 * 本来はここが本部サーバーへのPOST/GETに置き換わる想定(申し送り事項を参照)。
 *
 * Incidentそのもの(id)は、報告(Observation)のうちメモが入力されているものを
 * インシデントとして扱う決定事項1の方針に合わせ、Observationのidをそのまま
 * IncidentのidとしてキーにするApproach(frontend/src/utils/incidents.js参照)。
 */
function readStates() {
  return loadJson(STORAGE_KEYS.incidentStates, {});
}

function writeStates(states) {
  localStorage.setItem(STORAGE_KEYS.incidentStates, JSON.stringify(states));
}

const DEFAULT_STATE = { confirmStatus: "UNCONFIRMED", resolutionRequest: null, resolution: null };

/** 指定したIncident(=Observation)のローカル状態を取得する。未保存なら初期状態を返す。 */
export function getIncidentState(incidentId) {
  return readStates()[incidentId] || DEFAULT_STATE;
}

/**
 * モバイルからの「対応済みにする」申請(決定事項12・23)。
 * 本部の承認が下りるまでは resolution は確定しない。
 */
export function requestResolution(incidentId, { memo, staffName, targetShelterId, activeShelterId }) {
  const states = readStates();
  states[incidentId] = {
    ...getIncidentState(incidentId),
    resolutionRequest: {
      memo,
      staffName,
      targetShelterId,
      activeShelterId,
      requestedAt: new Date().toISOString(),
    },
  };
  writeStates(states);
  return states[incidentId];
}

/** PC(本部)専用の「確認済みにする」(決定事項14)。 */
export function confirmIncident(incidentId, { approverName, memo }) {
  const states = readStates();
  states[incidentId] = {
    ...getIncidentState(incidentId),
    confirmStatus: "CONFIRMED",
    confirmedBy: approverName,
    confirmMemo: memo,
    confirmedAt: new Date().toISOString(),
  };
  writeStates(states);
  return states[incidentId];
}

/**
 * PC(本部)が申請を経由せず直接「対応済みにする」場合(決定事項14: PC専用操作)。
 * 承認者本人がその場で対応内容を記録するため、承認待ちを経由せず即確定する。
 */
export function resolveIncidentDirectly(incidentId, { approverName, memo, staffName }) {
  const states = readStates();
  states[incidentId] = {
    ...getIncidentState(incidentId),
    resolution: { memo, staffName, approverName, approvedAt: new Date().toISOString() },
  };
  writeStates(states);
  return states[incidentId];
}

/** モバイルからの申請を、PC(本部)が承認して確定する(決定事項2・7・12)。 */
export function approveResolutionRequest(incidentId, { approverName }) {
  const states = readStates();
  const current = getIncidentState(incidentId);
  if (!current.resolutionRequest) return current;
  states[incidentId] = {
    ...current,
    resolution: {
      memo: current.resolutionRequest.memo,
      staffName: current.resolutionRequest.staffName,
      approverName,
      approvedAt: new Date().toISOString(),
    },
  };
  writeStates(states);
  return states[incidentId];
}
