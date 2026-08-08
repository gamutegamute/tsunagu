import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import IncidentManagementTab from "./IncidentManagementTab.jsx";
import { fetchIncidents } from "../api.js";

vi.mock("../api.js", () => ({
  fetchIncidents: vi.fn(),
}));

function makeApiIncident(overrides = {}) {
  return {
    id: "OBS-001",
    shelter: { id: "AIT001", name: "Shelter A", location: "", created_at: "2026-07-01T00:00:00Z" },
    urgency: "WARNING",
    memo: "未確認インシデント",
    observed_at: "2026-07-15T00:00:00Z",
    state: {
      confirm_status: "UNCONFIRMED",
      confirmed_by: null,
      confirmed_at: null,
      confirm_memo: null,
      resolution_request_memo: null,
      resolution_request_staff_name: null,
      resolution_request_active_shelter_id: null,
      resolution_request_at: null,
      resolution_memo: null,
      resolution_staff_name: null,
      resolution_approver_name: null,
      resolution_approved_at: null,
    },
    ...overrides,
  };
}

function renderWithIncidents(incidents) {
  fetchIncidents.mockResolvedValue(incidents);
  return render(<IncidentManagementTab />);
}

describe("IncidentManagementTab", () => {
  beforeEach(() => {
    fetchIncidents.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("未確認→一覧→確認済み→対応済みの順で4タブを表示する", async () => {
    renderWithIncidents([]);

    await screen.findByText("該当するインシデントはありません");
    const tabLabels = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((text) => ["未確認", "一覧", "確認済み", "対応済み"].includes(text));

    expect(tabLabels).toEqual(["未確認", "一覧", "確認済み", "対応済み"]);
  });

  it("同一避難所の複数インシデントを一覧タブで両方表示する", async () => {
    renderWithIncidents([
      makeApiIncident({ id: "OBS-001", memo: "1件目のインシデント(水不足)" }),
      makeApiIncident({ id: "OBS-002", memo: "2件目のインシデント(同じ避難所・停電)" }),
    ]);

    await screen.findByText("1件目のインシデント(水不足)");
    fireEvent.click(screen.getByRole("button", { name: "一覧" }));

    expect(screen.getByText("1件目のインシデント(水不足)")).not.toBeNull();
    expect(screen.getByText("2件目のインシデント(同じ避難所・停電)")).not.toBeNull();
  });

  it("各タブで未確認・確認済み・対応済みを正しく絞り込む", async () => {
    renderWithIncidents([
      makeApiIncident({ id: "OBS-001", memo: "未確認のインシデント" }),
      makeApiIncident({
        id: "OBS-002",
        memo: "確認済みのインシデント",
        state: { ...makeApiIncident().state, confirm_status: "CONFIRMED", confirmed_by: "本部 太郎" },
      }),
      makeApiIncident({
        id: "OBS-003",
        memo: "対応済みのインシデント",
        state: {
          ...makeApiIncident().state,
          resolution_approved_at: "2026-07-15T02:00:00Z",
          resolution_approver_name: "本部 太郎",
        },
      }),
    ]);

    await screen.findByText("未確認のインシデント");
    expect(screen.queryByText("確認済みのインシデント")).toBeNull();
    expect(screen.queryByText("対応済みのインシデント")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "確認済み" }));
    await waitFor(() => expect(screen.getByText("確認済みのインシデント")).not.toBeNull());
    expect(screen.queryByText("未確認のインシデント")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "対応済み" }));
    await waitFor(() => expect(screen.getByText("対応済みのインシデント")).not.toBeNull());
    expect(screen.queryByText("確認済みのインシデント")).toBeNull();
  });
});
