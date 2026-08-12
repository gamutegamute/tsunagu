import "fake-indexeddb/auto";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useOfflineReportQueue } from "./useOfflineReportQueue.js";
import { createObservation } from "../api.js";
import { getSentReportHistory } from "../utils/sentReportHistory.js";
import { getPendingReports, removePendingReport } from "../utils/pendingReports.js";

vi.mock("../api.js", () => ({
  createObservation: vi.fn(),
}));

function makeReport(overrides = {}) {
  return {
    shelter_id: "AIT001",
    client_event_id: "evt-1",
    people_count: 50,
    water_stock: 20,
    urgency: "NORMAL",
    memo: "",
    observed_at: "2026-08-06T01:00:00.000Z",
    source: "offline",
    ...overrides,
  };
}

async function clearQueue() {
  for (const report of await getPendingReports()) {
    await removePendingReport(report.client_event_id);
  }
}

describe("useOfflineReportQueue", () => {
  beforeEach(async () => {
    localStorage.clear();
    await clearQueue();
    createObservation.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("adds a report to the durable queue", async () => {
    const { result } = renderHook(() => useOfflineReportQueue());

    await act(async () => {
      await result.current.addReportToPendingQueue(makeReport());
    });

    expect(result.current.pendingReportCount).toBe(1);
    await expect(getPendingReports()).resolves.toEqual([makeReport()]);
  });

  it("removes only successfully resent reports", async () => {
    createObservation.mockImplementation((report) => {
      if (report.client_event_id === "evt-fail") return Promise.reject(new Error("network error"));
      return Promise.resolve({});
    });
    const { result } = renderHook(() => useOfflineReportQueue());

    await act(async () => {
      await result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-ok" }));
      await result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-fail" }));
      await result.current.sendPendingReports();
    });

    expect(result.current.pendingReportCount).toBe(1);
    await expect(getPendingReports()).resolves.toEqual([makeReport({ client_event_id: "evt-fail" })]);
    expect(getSentReportHistory()).toHaveLength(1);
  });

  it("keeps a report added while another report is syncing", async () => {
    let finishFirstRequest;
    createObservation.mockImplementation(() => new Promise((resolve) => {
      finishFirstRequest = resolve;
    }));
    const { result } = renderHook(() => useOfflineReportQueue());

    await act(async () => {
      await result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-first" }));
    });

    let syncPromise;
    act(() => {
      syncPromise = result.current.sendPendingReports();
    });
    await waitFor(() => expect(createObservation).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-later" }));
      finishFirstRequest({});
      await syncPromise;
    });

    await expect(getPendingReports()).resolves.toEqual([makeReport({ client_event_id: "evt-later" })]);
  });
});
