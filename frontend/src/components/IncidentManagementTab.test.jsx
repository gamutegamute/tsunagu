import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
    memo: "デフォルトのメモ",
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

describe("IncidentManagementTab(決定事項34-a/34-b: GET /api/incidents連携)", () => {
  beforeEach(() => {
    fetchIncidents.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("同一避難所の複数インシデントが、両方とも一覧に表示される(決定事項34-aがUI上でも機能することの確認)", async () => {
    fetchIncidents.mockResolvedValue([
      makeApiIncident({ id: "OBS-001", memo: "1件目のインシデント(水不足)" }),
      makeApiIncident({ id: "OBS-002", memo: "2件目のインシデント(同じ避難所・停電)" }),
    ]);

    render(<IncidentManagementTab />);

    await waitFor(() => expect(screen.getByText("1件目のインシデント(水不足)")).not.toBeNull());
    expect(screen.getByText("2件目のインシデント(同じ避難所・停電)")).not.toBeNull();
  });

  it("インシデントが無い場合は空状態メッセージを表示する", async () => {
    fetchIncidents.mockResolvedValue([]);

    render(<IncidentManagementTab />);

    await waitFor(() => expect(screen.getByText("該当するインシデントはありません")).not.toBeNull());
  });

  it("未確認タブ(デフォルト)では、確認済み・対応済みのインシデントは表示しない", async () => {
    fetchIncidents.mockResolvedValue([
      makeApiIncident({ id: "OBS-001", memo: "未確認のインシデント" }),
      makeApiIncident({
        id: "OBS-002",
        memo: "確認済みのインシデント",
        state: { ...makeApiIncident().state, confirm_status: "CONFIRMED", confirmed_by: "本部 太郎" },
      }),
    ]);

    render(<IncidentManagementTab />);

    await waitFor(() => expect(screen.getByText("未確認のインシデント")).not.toBeNull());
    expect(screen.queryByText("確認済みのインシデント")).toBeNull();
  });
});
