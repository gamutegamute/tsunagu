import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import IncidentManagementTab from "./IncidentManagementTab.jsx";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

const shelterStatusList = [
  {
    shelter: { id: "AIT001", name: "Shelter A" },
    status: "NORMAL",
    latest_observation: {
      id: "obs-1",
      memo: "未確認インシデント",
      observed_at: "2026-08-06T01:00:00.000Z",
      source: "field_report",
    },
  },
  {
    shelter: { id: "AIT002", name: "Shelter B" },
    status: "WARNING",
    latest_observation: {
      id: "obs-2",
      memo: "確認済みインシデント",
      observed_at: "2026-08-06T01:00:00.000Z",
      source: "field_report",
    },
  },
  {
    shelter: { id: "AIT003", name: "Shelter C" },
    status: "ALERT",
    latest_observation: {
      id: "obs-3",
      memo: "対応済みインシデント",
      observed_at: "2026-08-06T01:00:00.000Z",
      source: "field_report",
    },
  },
];

function seedIncidentStates() {
  localStorage.setItem(
    STORAGE_KEYS.incidentStates,
    JSON.stringify({
      "obs-2": { confirmStatus: "CONFIRMED", resolutionRequest: null, resolution: null },
      "obs-3": {
        confirmStatus: "UNCONFIRMED",
        resolutionRequest: null,
        resolution: { memo: "対応済メモ", staffName: "現場担当", approverName: "本部担当", approvedAt: "2026-08-06T02:00:00.000Z" },
      },
    }),
  );
}

describe("IncidentManagementTab(決定事項33-e: 4タブ構成)", () => {
  beforeEach(() => {
    localStorage.clear();
    seedIncidentStates();
  });

  afterEach(() => {
    cleanup();
  });

  it("未確認→一覧→確認済み→対応済みの順で4タブ表示する", () => {
    render(<IncidentManagementTab shelterStatusList={shelterStatusList} />);

    const tabLabels = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((text) => ["未確認", "一覧", "確認済み", "対応済み"].includes(text));

    expect(tabLabels).toEqual(["未確認", "一覧", "確認済み", "対応済み"]);
  });

  it("初期表示(未確認タブ)では未確認のインシデントのみ表示する", () => {
    render(<IncidentManagementTab shelterStatusList={shelterStatusList} />);

    expect(screen.getByText(/Shelter A/)).not.toBeNull();
    expect(screen.queryByText(/Shelter B/)).toBeNull();
    expect(screen.queryByText(/Shelter C/)).toBeNull();
  });

  it("「一覧」タブでは状態を問わず全インシデントを表示する", () => {
    render(<IncidentManagementTab shelterStatusList={shelterStatusList} />);

    fireEvent.click(screen.getByRole("button", { name: "一覧" }));

    expect(screen.getByText(/Shelter A/)).not.toBeNull();
    expect(screen.getByText(/Shelter B/)).not.toBeNull();
    expect(screen.getByText(/Shelter C/)).not.toBeNull();
  });

  it("「確認済み」タブでは確認済みのインシデントのみ表示する", () => {
    render(<IncidentManagementTab shelterStatusList={shelterStatusList} />);

    fireEvent.click(screen.getByRole("button", { name: "確認済み" }));

    expect(screen.queryByText(/Shelter A/)).toBeNull();
    expect(screen.getByText(/Shelter B/)).not.toBeNull();
    expect(screen.queryByText(/Shelter C/)).toBeNull();
  });

  it("「対応済み」タブでは対応済みのインシデントのみ表示する", () => {
    render(<IncidentManagementTab shelterStatusList={shelterStatusList} />);

    fireEvent.click(screen.getByRole("button", { name: "対応済み" }));

    expect(screen.queryByText(/Shelter A/)).toBeNull();
    expect(screen.queryByText(/Shelter B/)).toBeNull();
    expect(screen.getByText(/Shelter C/)).not.toBeNull();
  });
});
