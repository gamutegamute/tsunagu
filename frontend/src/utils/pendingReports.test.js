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

function journalEntry(id) {
  return JSON.parse(localStorage.getItem(`${STORAGE_KEYS.pendingReportsFallback}.report.${encodeURIComponent(id)}`));
}

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
    expect(journalEntry(report.client_event_id).report).toEqual(report);
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
    expect(journalEntry(report.client_event_id).report).toBeNull();
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

  async function independentStores() {
    vi.resetModules();
    const offlineTab = await import("./pendingReports.js");
    await offlineTab.getPendingReports();
    const fail = vi.spyOn(IDBDatabase.prototype, "transaction").mockImplementation(() => { throw new Error("unavailable"); });
    await offlineTab.getPendingReports();
    fail.mockRestore();
    vi.resetModules();
    return { offlineTab, recoveringTab: await import("./pendingReports.js") };
  }

  it("preserves a report saved by another window during recovery without Web Locks", async () => {
    const { offlineTab, recoveringTab } = await independentStores();
    const second = { ...report, client_event_id: "other-window" };
    localStorage.setItem(STORAGE_KEYS.pendingReportsFallback, JSON.stringify({ [report.client_event_id]: report }));
    const put = IDBObjectStore.prototype.put;
    let addition;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (value) {
      const request = put.call(this, value);
      if (value.client_event_id === report.client_event_id) {
        request.addEventListener("success", () => { addition = offlineTab.addPendingReport(second); });
      }
      return request;
    });
    await recoveringTab.getPendingReports();
    await addition;
    expect(journalEntry(second.client_event_id).report).toEqual(second);
    await expect(recoveringTab.getPendingReports()).resolves.toEqual(expect.arrayContaining([report, second]));
  });

  it("keeps a replacement deletion written while a journal entry is being recovered", async () => {
    const { offlineTab, recoveringTab } = await independentStores();
    await offlineTab.addPendingReport(report);
    const put = IDBObjectStore.prototype.put;
    let deletion;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (value) {
      const request = put.call(this, value);
      request.addEventListener("success", () => { deletion = offlineTab.removePendingReport(value.client_event_id); });
      return request;
    });
    await recoveringTab.getPendingReports();
    await deletion;
    expect(journalEntry(report.client_event_id).report).toBeNull();
    await expect(recoveringTab.getPendingReports()).resolves.toEqual([]);
  });

  it("serializes independent windows with the same Web Lock", async () => {
    let tail = Promise.resolve();
    const requestLock = vi.fn((name, operation) => {
      const result = tail.then(operation);
      tail = result.catch(() => {});
      return result;
    });
    Object.defineProperty(navigator, "locks", { configurable: true, value: { request: requestLock } });
    try {
      const { offlineTab, recoveringTab } = await independentStores();
      const second = { ...report, client_event_id: "locked-window" };
      await offlineTab.addPendingReport(report);
      const put = IDBObjectStore.prototype.put;
      let addition;
      vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (value) {
        const req = put.call(this, value);
        if (value.client_event_id === report.client_event_id) req.addEventListener("success", () => { addition = offlineTab.addPendingReport(second); });
        return req;
      });
      await recoveringTab.getPendingReports();
      await addition;
      await expect(recoveringTab.getPendingReports()).resolves.toEqual(expect.arrayContaining([report, second]));
      expect(requestLock.mock.calls.every(([name]) => name === "tsunagu-pending-reports")).toBe(true);
    } finally {
      delete navigator.locks;
    }
  });
});
