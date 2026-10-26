import { useState } from "react";
import IncidentCard from "./IncidentCard.jsx";
import PcActionModal from "./PcActionModal.jsx";
import { isResolved, isPendingApproval, describeIncidentDisplay } from "../../utils/incidents.js";
import { confirmIncident, resolveIncidentDirectly, approveResolutionRequest } from "../../utils/incidentStore.js";
import { getApproverName } from "../../utils/approverName.js";
import { useAuth } from "../../auth/AuthContext.jsx";
import { canOperateShelter } from "../../utils/shelterPermissions.js";

/**
 * PC(本部)向けのIncidentカード(決定事項1・2・7・12・14)。
 * Shelter Detail画面とインシデント管理タブの両方から使う共通部品。
 */
export default function PcIncidentCard({ incident, onChanged }) {
  const [activeModal, setActiveModal] = useState(null); // "confirm" | "resolve" | null
  const [error, setError] = useState("");
  const [approving, setApproving] = useState(false);
  const { user } = useAuth();
  const approverName = getApproverName();
  const { assigneeLabel, statusNote, resolutionInfo } = describeIncidentDisplay(incident);

  async function handleApprove() {
    setApproving(true);
    setError("");
    try {
      await approveResolutionRequest(incident.id, { approverName, requestVersion: incident.resolutionRequest.version });
      await onChanged();
    } catch (error) {
      setError(error.status === 409 ? "申請内容が更新されたか、すでに承認されています。最新の内容を確認してください。" : "承認できませんでした。通信と権限を確認してください。");
      if (error.status === 409) await onChanged();
    } finally {
      setApproving(false);
    }
  }

  async function handleConfirmSubmit(memo) {
    await confirmIncident(incident.id, { approverName, memo });
    setActiveModal(null);
    onChanged();
  }

  async function handleResolveSubmit(memo) {
    await resolveIncidentDirectly(incident.id, { approverName, memo, staffName: approverName });
    setActiveModal(null);
    onChanged();
  }

  const pending = isPendingApproval(incident);
  const resolved = isResolved(incident);

  const actions =
    !resolved && user?.role === "hq" && canOperateShelter(user, incident.shelter.id) &&
    (pending ? (
      <button type="button" className="primary-button" onClick={handleApprove} disabled={approving}>
        承認する(本部)
      </button>
    ) : (
      <>
        {incident.confirmStatus !== "CONFIRMED" && (
          <button type="button" className="outline-button" onClick={() => setActiveModal("confirm")}>
            確認済みにする
          </button>
        )}
        <button type="button" className="primary-button" onClick={() => setActiveModal("resolve")}>
          対応済みにする
        </button>
      </>
    ));

  return (
    <>
      <IncidentCard
        incident={incident}
        variant="pc"
        assigneeLabel={assigneeLabel}
        statusNote={statusNote}
        resolutionInfo={resolutionInfo}
        actions={actions}
      />
      {pending && <p>申請内容: {incident.resolutionRequest.memo}</p>}
      {error && <p role="alert">{error}</p>}

      {activeModal === "confirm" && (
        <PcActionModal
          title="確認済みにする"
          subtitle={`対象: ${incident.shelter.id} ${incident.shelter.name}`}
          confirmLabel="確認済みにする"
          onCancel={() => setActiveModal(null)}
          onSubmit={handleConfirmSubmit}
        />
      )}
      {activeModal === "resolve" && (
        <PcActionModal
          title="対応済みにする"
          subtitle={`対象: ${incident.shelter.id} ${incident.shelter.name}`}
          confirmLabel="対応済みにする"
          onCancel={() => setActiveModal(null)}
          onSubmit={handleResolveSubmit}
        />
      )}
    </>
  );
}
