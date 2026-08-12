import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import {
  addPendingReport,
  getPendingReportCount,
  getPendingReports,
  removePendingReport,
} from "./pendingReports.js";
import { STORAGE_KEYS } from "./storageKeys.js";

const report = {
  client_event_id: "event-1",
  shelter_id: "AIT001",
  urgency: "WARNING",
  observed_at: "2026-08-06T02:00:00.000Z",
};

async function clearQueue() {
  for (const item of await getPendingReports()) {
    await removePendingReport(item.client_event_id);
  }
}

describe("pending report store", () => {
  beforeEach(async () => {
    localStorage.clear();
    await clearQueue();
  });

  it("starts empty", async () => {
    await expect(getPendingReports()).resolves.toEqual([]);
  });

  it("migrates the legacy localStorage queue once", async () => {
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify([report]));
    localStorage.removeItem(STORAGE_KEYS.pendingReportsMigrated);

    await expect(getPendingReports()).resolves.toEqual([report]);
    expect(localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated)).toBe("true");
  });

  it("uses client_event_id as an idempotent key", async () => {
    await addPendingReport(report);
    await addPendingReport({ ...report, urgency: "ALERT" });

    await expect(getPendingReportCount()).resolves.toBe(1);
    await expect(getPendingReports()).resolves.toEqual([{ ...report, urgency: "ALERT" }]);
  });
});
