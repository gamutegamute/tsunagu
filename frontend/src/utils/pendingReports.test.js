import { beforeEach, describe, expect, it } from "vitest";
import { getPendingReports } from "./pendingReports.js";
import { STORAGE_KEYS } from "./storageKeys.js";

describe("getPendingReports", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("何も保存されていない場合は空配列を返す", () => {
    expect(getPendingReports()).toEqual([]);
  });

  it("保存されているpendingReportsをそのまま返す", () => {
    const reports = [
      { shelter_id: "AIT001", urgency: "ALERT", observed_at: "2026-08-06T02:00:00.000Z" },
    ];
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify(reports));

    expect(getPendingReports()).toEqual(reports);
  });
});
