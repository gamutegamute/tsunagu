import "fake-indexeddb/auto";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useOfflineReportQueue } from "./useOfflineReportQueue.js";
import { addPendingReport, getPendingReports, removePendingReport, resetPendingReportStoreForTests } from "../utils/pendingReports.js";

const report = (id) => ({ client_event_id: id, shelter_id: "AIT001", people_count: 1, water_stock: 100, urgency: "NORMAL", memo: "救援", observed_at: new Date().toISOString(), source: "offline" });
const response = (payload) => new Response(JSON.stringify({ ...payload, id: `OBS-${payload.client_event_id}` }), { status: 201 });
beforeEach(async () => {
  resetPendingReportStoreForTests();
  localStorage.clear();
  for (const item of await getPendingReports()) await removePendingReport(item.client_event_id);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("keeps a report queued when the real API client receives an HTML success page", async () => {
  await addPendingReport(report("html"));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Maintenance</html>", { status: 200 })));
  const { result } = renderHook(() => useOfflineReportQueue());
  await act(async () => { await result.current.sendPendingReports(); });
  expect(result.current.pendingReportCount).toBe(1);
  expect((await getPendingReports())[0].client_event_id).toBe("html");
});

it("times out one report, sends the next, and retries the same ID after an ambiguous acceptance", async () => {
  const first = report("first"), second = report("second");
  await addPendingReport(first);
  await addPendingReport(second);
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
  const accepted = new Map();
  const ids = [];
  vi.stubGlobal("fetch", vi.fn((_, options) => {
    const payload = JSON.parse(options.body);
    ids.push(payload.client_event_id);
    if (!accepted.has(payload.client_event_id)) accepted.set(payload.client_event_id, payload);
    if (ids.length === 1) return new Promise(() => {}); // Accepted, but response never arrives.
    return Promise.resolve(response(accepted.get(payload.client_event_id)));
  }));
  const { result } = renderHook(() => useOfflineReportQueue());
  let sync;
  await act(async () => { sync = result.current.sendPendingReports(); await getPendingReports(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(15000); await sync; });
  expect(result.current.isSyncing).toBe(false);
  expect((await getPendingReports()).map((item) => item.client_event_id)).toEqual(["first"]);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  await act(async () => { await getPendingReports(); await getPendingReports(); });
  await expect(getPendingReports()).resolves.toEqual([]);
  expect(ids).toEqual(["first", "second", "first"]);
  expect(accepted.size).toBe(2);
});

it("shows unknown count on read failure and sends saved reports after storage recovers", async () => {
  await addPendingReport(report("stored"));
  const fail = vi.spyOn(IDBObjectStore.prototype, "getAll").mockImplementation(() => { throw new DOMException("temporary", "UnknownError"); });
  const { result } = renderHook(() => useOfflineReportQueue());
  await waitFor(() => expect(result.current.syncError).toContain("全件を読み出せません"));
  expect(result.current.pendingReportCount).toBeNull();
  fail.mockRestore();
  vi.stubGlobal("fetch", vi.fn((_, options) => Promise.resolve(response(JSON.parse(options.body)))));
  await act(async () => { await result.current.sendPendingReports(); });
  expect(result.current.pendingReportCount).toBe(0);
  expect(result.current.syncError).toBe("");
});
