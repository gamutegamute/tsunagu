import { useState } from "react";
import { useNavigate } from "react-router-dom";
import DashboardTabs from "./DashboardTabs.jsx";
import ShelterSearchAndSort from "./ShelterSearchAndSort.jsx";
import ShelterFilterChips from "./ShelterFilterChips.jsx";
import DashboardSummary from "./DashboardSummary.jsx";
import ShelterCard from "./ShelterCard.jsx";
import IncidentManagementTab from "./IncidentManagementTab.jsx";
import AddShelterModal from "./AddShelterModal.jsx";
import { useShelterFilters } from "../hooks/useShelterFilters.js";

/** 本部ダッシュボード全体(Figmaの Headquarters Dashboard 画面を再現)。 */
export default function Dashboard({ shelterStatusList, onSyncButtonClick }) {
  const navigate = useNavigate();
  const [activeTabId, setActiveTabId] = useState("status");
  const [isAddShelterModalOpen, setIsAddShelterModalOpen] = useState(false);
  const {
    searchText,
    setSearchText,
    urgencyFilter,
    setUrgencyFilter,
    requestCodeFilter,
    setRequestCodeFilter,
    sortOrder,
    setSortOrder,
    filteredAndSortedList,
  } = useShelterFilters(shelterStatusList);

  return (
    <section className="panel dashboard-panel">
      <div className="section-title">
        <h2>本部ダッシュボード</h2>
        <div className="dashboard-header-actions">
          <button type="button" className="outline-button" onClick={() => navigate("/dashboard/timeline")}>
            Timeline
          </button>
          <button type="button" id="syncButton" onClick={onSyncButtonClick}>
            同期
          </button>
        </div>
      </div>

      <DashboardTabs activeTabId={activeTabId} onChangeTab={setActiveTabId} />

      {activeTabId === "status" ? (
        <>
          <div className="section-header-row">
            <h3>状況一覧</h3>
            <button type="button" className="add-shelter-button" onClick={() => setIsAddShelterModalOpen(true)}>
              ＋ 避難所を追加
            </button>
          </div>

          <ShelterSearchAndSort
            searchText={searchText}
            onSearchTextChange={setSearchText}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
          />
          <ShelterFilterChips
            urgencyFilter={urgencyFilter}
            onUrgencyFilterChange={setUrgencyFilter}
            requestCodeFilter={requestCodeFilter}
            onRequestCodeFilterChange={setRequestCodeFilter}
          />

          <DashboardSummary shelterStatusList={shelterStatusList} />

          <div className="shelter-grid">
            {filteredAndSortedList.map((shelterStatus) => (
              <ShelterCard
                key={shelterStatus.shelter.id}
                shelterStatus={shelterStatus}
                onClick={() => navigate(`/dashboard/shelters/${shelterStatus.shelter.id}`)}
              />
            ))}
          </div>
        </>
      ) : (
        <IncidentManagementTab shelterStatusList={shelterStatusList} />
      )}

      {isAddShelterModalOpen && (
        <AddShelterModal
          onCancel={() => setIsAddShelterModalOpen(false)}
          onCreated={() => {
            setIsAddShelterModalOpen(false);
            onSyncButtonClick();
          }}
        />
      )}
    </section>
  );
}
