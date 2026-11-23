import { afterEach, expect, it, vi } from "vitest";
import { API_TIMEOUT_MS, ApiResponseError, createObservation, logout } from "./api.js";
const payload = { client_event_id: "evt-response", shelter_id: "AIT001", people_count: 1, water_stock: 20, urgency: "NORMAL", memo: "help" };
const accepted = { ...payload, id: "OBS-1", observed_at: "2026-10-28T00:00:00Z" };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
it.each([
  ["text/html", "<html>Maintenance</html>", 200],
  ["application/json", "{", 200],
  ["application/json", "null", 200],
  ["application/json", "{}", 200],
  ["application/json", null, 204],
  ["application/json", JSON.stringify({ ...accepted, client_event_id: "other" }), 201],
  ["application/json", JSON.stringify({ ...accepted, water_stock: 100 }), 201],
])("does not acknowledge invalid observation response %s %s", async (type, body, status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status, headers: { "Content-Type": type } })));
  await expect(createObservation(payload)).rejects.toBeInstanceOf(ApiResponseError);
});
it("accepts a matching idempotent response and intentional 204 logout", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(accepted), { status: 201 }))
    .mockResolvedValueOnce(new Response(null, { status: 204 })));
  await expect(createObservation(payload)).resolves.toEqual(accepted);
  await expect(logout()).resolves.toBeNull();
});
it("bounds the entire response wait even if fetch ignores abort", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetch);
  const promise = expect(createObservation(payload)).rejects.toThrow("タイムアウト");
  await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS);
  await promise;
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
});
it("also times out a response whose body never completes", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 201, json: () => new Promise(() => {}) }));
  const promise = expect(createObservation(payload)).rejects.toThrow("タイムアウト");
  await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS);
  await promise;
});
