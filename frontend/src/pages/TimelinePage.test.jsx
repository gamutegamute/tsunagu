import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import TimelinePage from "./TimelinePage.jsx";
import { fetchDashboard, fetchEmergencyPackets, fetchShelterObservations } from "../api.js";

vi.mock("../api.js", () => ({
  fetchDashboard: vi.fn(),
  fetchEmergencyPackets: vi.fn(),
  fetchShelterObservations: vi.fn(),
}));

vi.mock("../hooks/useShelterList.js", () => ({
  useShelterList: () => [
    { id: "AIT001", name: "Shelter A" },
    { id: "AIT002", name: "Shelter B" },
  ],
}));

function dashboardItem(shelterId, shelterName, observationId, observedAt, memo) {
  return {
    shelter: { id: shelterId, name: shelterName, location: "", created_at: "2026-07-01T00:00:00Z" },
    latest_observation: {
      id: observationId,
      people_count: 10,
      water_stock: 5,
      urgency: "NORMAL",
      memo,
      reporter_name: "報告者",
      observed_at: observedAt,
      source: "web",
    },
    status: "NORMAL",
    request_code: null,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TimelinePage />
    </MemoryRouter>,
  );
}

describe("TimelinePage(過去の報告履歴を遡って見る機能)", () => {
  beforeEach(() => {
    fetchDashboard.mockReset();
    fetchEmergencyPackets.mockReset();
    fetchShelterObservations.mockReset();
    fetchEmergencyPackets.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("避難所ごとに最新1件をグルーピングして表示し、廃止済みの案内文言は表示しない", async () => {
    fetchDashboard.mockResolvedValue([
      dashboardItem("AIT001", "Shelter A", "OBS-1", "2026-08-09T03:00:00.000Z", "最新報告A"),
      dashboardItem("AIT002", "Shelter B", "OBS-2", "2026-08-09T02:00:00.000Z", "最新報告B"),
    ]);

    renderPage();

    await screen.findByText("最新報告A");
    expect(screen.getByText("最新報告B")).not.toBeNull();
    // 避難所ごとに1行(グループ)のみ。過去の報告を見る、のトグルが避難所数と同じ2つあること
    expect(screen.getAllByRole("button", { name: /過去の報告を見る/ })).toHaveLength(2);

    expect(screen.queryByText(/過去の報告履歴を遡って見るAPIは今後追加予定です/)).toBeNull();
  });

  it("避難所の「過去の報告を見る」を押すと、その避難所の履歴APIが避難所IDで呼ばれ、過去の報告が表示される", async () => {
    fetchDashboard.mockResolvedValue([
      dashboardItem("AIT001", "Shelter A", "OBS-1", "2026-08-09T03:00:00.000Z", "最新報告A"),
    ]);
    fetchShelterObservations.mockResolvedValue([
      {
        id: "OBS-1",
        people_count: 10,
        water_stock: 5,
        urgency: "NORMAL",
        memo: "最新報告A",
        reporter_name: "報告者",
        observed_at: "2026-08-09T03:00:00.000Z",
        source: "web",
      },
      {
        id: "OBS-0",
        people_count: 8,
        water_stock: 6,
        urgency: "NORMAL",
        memo: "過去の報告A",
        reporter_name: "報告者",
        observed_at: "2026-08-08T03:00:00.000Z",
        source: "web",
      },
    ]);

    renderPage();
    await screen.findByText("最新報告A");

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));

    expect(fetchShelterObservations).toHaveBeenCalledWith("AIT001");
    await waitFor(() => expect(screen.getByText("過去の報告A")).not.toBeNull());
  });

  it("報告が1件もない場合は空状態メッセージを表示する", async () => {
    fetchDashboard.mockResolvedValue([]);

    renderPage();

    await screen.findByText("報告履歴はまだありません");
  });
});
