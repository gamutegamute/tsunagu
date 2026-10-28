import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboardData } from "./useDashboardData.js";
import { fetchDashboard, fetchEmergencyPackets } from "../api.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

vi.mock("../api.js", () => ({
  fetchDashboard: vi.fn(),
  fetchEmergencyPackets: vi.fn(),
}));

function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("useDashboardData(決定事項34-c: reloadDashboardのin-flightガード)", () => {
  beforeEach(() => {
    localStorage.clear();
    fetchDashboard.mockReset();
    fetchEmergencyPackets.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("実行中に重ねてreloadDashboardを呼んでも、fetchDashboardは1回しか呼ばれず、同じPromiseが返る", async () => {
    const dashboardDeferred = deferred();
    fetchDashboard.mockReturnValue(dashboardDeferred.promise);
    fetchEmergencyPackets.mockResolvedValue([]);

    const { result } = renderHook(() => useDashboardData());

    let firstCallPromise;
    let secondCallPromise;
    act(() => {
      firstCallPromise = result.current.reloadDashboard();
      secondCallPromise = result.current.reloadDashboard();
    });

    expect(fetchDashboard).toHaveBeenCalledTimes(1);
    expect(firstCallPromise).toBe(secondCallPromise);

    await act(async () => {
      dashboardDeferred.resolve([{ shelter: { id: "AIT001" }, latest_observation: null }]);
      await firstCallPromise;
    });

    expect(fetchDashboard).toHaveBeenCalledTimes(1);
    expect(result.current.dashboardItems).toEqual([{ shelter: { id: "AIT001" }, latest_observation: null }]);
  });

  it("前回のreloadDashboardが完了した後に再度呼ぶと、新しいリクエストが発生する", async () => {
    fetchDashboard.mockResolvedValue([]);
    fetchEmergencyPackets.mockResolvedValue([]);

    const { result } = renderHook(() => useDashboardData());

    await act(async () => {
      await result.current.reloadDashboard();
    });
    await act(async () => {
      await result.current.reloadDashboard();
    });

    expect(fetchDashboard).toHaveBeenCalledTimes(2);
  });

  it("失敗した場合でも、その後の呼び出しはガードされずに新規リクエストとして実行される", async () => {
    fetchDashboard.mockRejectedValueOnce(new Error("network error"));
    fetchDashboard.mockResolvedValueOnce([]);
    fetchEmergencyPackets.mockResolvedValue([]);

    const { result } = renderHook(() => useDashboardData());

    await act(async () => {
      await result.current.reloadDashboard();
    });
    await act(async () => {
      await result.current.reloadDashboard();
    });

    expect(fetchDashboard).toHaveBeenCalledTimes(2);
  });

  it("marks stale cached reports and exposes failed refresh then recovers", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const item = { shelter: { id: "AIT001" }, latest_observation: { observed_at: new Date(Date.now() - 23 * 3600000).toISOString(), water_stock: 100 }, status: "NORMAL", request_code: null };
    localStorage.setItem(STORAGE_KEYS.cachedDashboard, JSON.stringify([item]));
    fetchDashboard.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([{ ...item, latest_observation: { ...item.latest_observation, observed_at: new Date().toISOString() } }]);
    fetchEmergencyPackets.mockResolvedValue([]);
    const { result } = renderHook(() => useDashboardData());
    expect(result.current.dashboardItems[0].status).toBe("NORMAL");
    await act(async () => { await vi.advanceTimersByTimeAsync(2 * 3600000); });
    expect(result.current.dashboardItems[0].status).toBe("ALERT");
    expect(result.current.dashboardItems[0].request_code).toBe("REQ_CONFIRM");
    await act(async () => { expect(await result.current.reloadDashboard()).toBe(false); });
    expect(result.current.isCached).toBe(true);
    expect(result.current.error).toContain("最新情報を取得できません");
    await act(async () => { expect(await result.current.reloadDashboard()).toBe(true); });
    expect(result.current.error).toBe("");
    expect(result.current.isCached).toBe(false);
    expect(result.current.lastSuccessAt).toBeTruthy();
    expect(result.current.dashboardItems[0].status).toBe("NORMAL");
  });
});
