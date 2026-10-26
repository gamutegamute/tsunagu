import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addPendingReport,
  getPendingReportCount,
  getPendingReports,
  removePendingReport,
  resetPendingReportStoreForTests,
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
    vi.restoreAllMocks();
    resetPendingReportStoreForTests();
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

  it("waits for commit, falling back when put succeeds but its transaction aborts", async () => {
    await getPendingReports();
    const put = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (...args) {
      const request = put.apply(this, args);
      request.addEventListener("success", () => this.transaction.abort());
      return request;
    });
    await addPendingReport(report);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.pendingReportsFallback))[report.client_event_id]).toEqual(report);
    vi.restoreAllMocks();
    resetPendingReportStoreForTests(); // Reload with a healthy IndexedDB.
    await expect(getPendingReports()).resolves.toEqual([report]);
    expect(localStorage.getItem(STORAGE_KEYS.pendingReportsFallback)).toBeNull();
    await removePendingReport(report.client_event_id);
    resetPendingReportStoreForTests();
    await expect(getPendingReports()).resolves.toEqual([]);
  });

  it("keeps a durable deletion if delete succeeds then aborts", async () => {
    await addPendingReport(report);
    const remove = IDBObjectStore.prototype.delete;
    vi.spyOn(IDBObjectStore.prototype, "delete").mockImplementation(function (...args) {
      const request = remove.apply(this, args);
      request.addEventListener("success", () => this.transaction.abort());
      return request;
    });
    await removePendingReport(report.client_event_id);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.pendingReportsFallback))[report.client_event_id]).toBeNull();
    vi.restoreAllMocks();
    resetPendingReportStoreForTests();
    await expect(getPendingReports()).resolves.toEqual([]);
  });

  it("does not mark an aborted migration as complete and retries without duplicates", async () => {
    localStorage.removeItem(STORAGE_KEYS.pendingReportsMigrated);
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify([report]));
    const put = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (...args) {
      const request = put.apply(this, args);
      request.addEventListener("success", () => this.transaction.abort());
      return request;
    });
    await expect(getPendingReports()).resolves.toEqual([report]);
    expect(localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated)).toBeNull();
    vi.restoreAllMocks();
    resetPendingReportStoreForTests();
    await expect(getPendingReports()).resolves.toEqual([report]);
    expect(localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated)).toBe("true");
  });

  it("ignores stale legacy copies after a completed migration", async () => {
    localStorage.setItem(STORAGE_KEYS.pendingReportsMigrated, "true");
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify([report]));
    await expect(getPendingReports()).resolves.toEqual([]);
  });

  it("retains the journal after a partial recovery and merges it idempotently on retry", async () => {
    const second = { ...report, client_event_id: "event-2" };
    localStorage.setItem(STORAGE_KEYS.pendingReportsFallback, JSON.stringify({ "event-1": report, "event-2": second }));
    const put = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (value) {
      const request = put.call(this, value);
      if (value.client_event_id === "event-2") request.addEventListener("success", () => this.transaction.abort());
      return request;
    });
    await expect(getPendingReports()).resolves.toHaveLength(2);
    expect(Object.keys(JSON.parse(localStorage.getItem(STORAGE_KEYS.pendingReportsFallback)))).toHaveLength(2);
    vi.restoreAllMocks();
    resetPendingReportStoreForTests();
    await expect(getPendingReports()).resolves.toHaveLength(2);
    await expect(getPendingReportCount()).resolves.toBe(2);
    expect(localStorage.getItem(STORAGE_KEYS.pendingReportsFallback)).toBeNull();
  });
});
