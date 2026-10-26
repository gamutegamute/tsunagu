import { useState } from "react";
import { useNavigate } from "react-router";
import StatusFilterTabs from "../components/incident/StatusFilterTabs.jsx";
import IncidentCard from "../components/incident/IncidentCard.jsx";
import ResolutionRequestModal from "../components/incident/ResolutionRequestModal.jsx";
import { useIncidents } from "../hooks/useIncidents.js";
import { useShelterList } from "../hooks/useShelterList.js";
import { canRequestResolution, isResolved, describeIncidentDisplay } from "../utils/incidents.js";
import { requestResolution } from "../utils/incidentStore.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { canOperateShelter } from "../utils/shelterPermissions.js";

const TABS = [
  { id: "unresolved", label: "未対応" },
  { id: "resolved", label: "対応済み" },
];

/**
 * モバイル向けIncident画面(/incident)。
 *
 * 決定事項2: 閲覧は全避難所ぶん自由(全エリア可)。
 * 決定事項14: モバイルにできるのは「対応済みにする」の申請までで、
 * 「確認済みにする」「承認する」ボタンは置かない(本部PC専用)。
 */
export default function IncidentPage() {
  const navigate = useNavigate();
  const shelters = useShelterList();
  const { incidents, refresh, error, loading } = useIncidents();
  const { user } = useAuth();
  const [activeTabId, setActiveTabId] = useState("unresolved");
  const [requestTargetIncident, setRequestTargetIncident] = useState(null);

  const visibleIncidents = incidents.filter((incident) =>
    activeTabId === "resolved" ? isResolved(incident) : !isResolved(incident),
  );

  async function handleRequestSubmit(formValues) {
    await requestResolution(requestTargetIncident.id, formValues);
    setRequestTargetIncident(null);
    refresh();
  }

  return (
    <>
      <header className="topbar incident-header">
        <div className="incident-header-title-row">
          <button type="button" className="icon-nav-button" onClick={() => navigate(-1)} aria-label="戻る">
            ←
          </button>
          <h1>インシデント</h1>
        </div>
        <div className="incident-header-subtitle-row">
          <span className="scope-badge">全避難所</span>
          <span className="incident-header-note">閲覧は全避難所・申請は担当避難所のみ・確定は本部が承認</span>
        </div>
      </header>

      <main className="layout-mobile">
        <StatusFilterTabs tabs={TABS} activeTabId={activeTabId} onChangeTab={setActiveTabId} />

        <div className="incident-card-list">
          {loading && <p role="status">読み込み中...</p>}
          {error && <p role="alert">{error}<button type="button" onClick={refresh}>再取得</button></p>}
          {!loading && !error && visibleIncidents.length === 0 && <p className="incident-empty-state">該当するインシデントはありません</p>}
          {visibleIncidents.map((incident) => {
            const { assigneeLabel, statusNote, resolutionInfo } = describeIncidentDisplay(incident);
            const showResolutionRequestButton = canRequestResolution(incident) && canOperateShelter(user, incident.shelter.id);
            return (
              <IncidentCard
                key={incident.id}
                incident={incident}
                variant="mobile"
                assigneeLabel={assigneeLabel}
                statusNote={statusNote}
                resolutionInfo={resolutionInfo}
                actions={
                  showResolutionRequestButton ? (
                    <button
                      type="button"
                      className="primary-button incident-resolve-button"
                      onClick={() => setRequestTargetIncident(incident)}
                    >
                      対応済みにする
                    </button>
                  ) : null
                }
              />
            );
          })}
        </div>
      </main>

      {requestTargetIncident && (
        <ResolutionRequestModal
          incident={requestTargetIncident}
          shelters={shelters}
          onCancel={() => setRequestTargetIncident(null)}
          onSubmit={handleRequestSubmit}
        />
      )}
    </>
  );
}
