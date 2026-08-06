import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useOfflineReportQueue } from "./useOfflineReportQueue.js";
import { createObservation } from "../api.js";
import { getSentReportHistory } from "../utils/sentReportHistory.js";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

vi.mock("../api.js", () => ({
  createObservation: vi.fn(),
}));

function readPendingReportsFromLocalStorage() {
  return JSON.parse(localStorage.getItem(STORAGE_KEYS.pendingReports) || "[]");
}

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

describe("useOfflineReportQueue(決定事項34-g: オフライン再送キューの中核ロジック)", () => {
  beforeEach(() => {
    localStorage.clear();
    createObservation.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("addReportToPendingQueue: 報告をキューへ追加し、pendingReportCountが増える", () => {
    const { result } = renderHook(() => useOfflineReportQueue());
    expect(result.current.pendingReportCount).toBe(0);

    act(() => {
      result.current.addReportToPendingQueue(makeReport());
    });

    expect(result.current.pendingReportCount).toBe(1);
    expect(readPendingReportsFromLocalStorage()).toEqual([makeReport()]);
  });

  it("addReportToPendingQueue: 複数件追加すると、末尾に順番通り積み上がる", () => {
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-1" }));
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-2" }));
    });

    expect(result.current.pendingReportCount).toBe(2);
    expect(readPendingReportsFromLocalStorage().map((r) => r.client_event_id)).toEqual(["evt-1", "evt-2"]);
  });

  it("sendPendingReports: 全件成功した場合、キューが空になり送信履歴に記録される(重複防止: キューに残らない)", async () => {
    createObservation.mockResolvedValue({});
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-1", shelter_id: "AIT001", urgency: "WARNING" }));
    });

    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(result.current.pendingReportCount).toBe(0);
    expect(readPendingReportsFromLocalStorage()).toEqual([]);
    expect(createObservation).toHaveBeenCalledTimes(1);

    const history = getSentReportHistory();
    expect(history).toHaveLength(1);
    expect(history[0]).toMatchObject({ shelterId: "AIT001", urgency: "WARNING", observedAt: "2026-08-06T01:00:00.000Z" });
  });

  it("sendPendingReports: shelter_idが無い場合、shelter_codeを送信履歴のshelterIdとして使う", async () => {
    createObservation.mockResolvedValue({});
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      const { shelter_id, ...withoutShelterId } = makeReport({ client_event_id: "evt-1" });
      result.current.addReportToPendingQueue({ ...withoutShelterId, shelter_code: "AIT002" });
    });

    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(getSentReportHistory()[0]).toMatchObject({ shelterId: "AIT002" });
  });

  it("sendPendingReports: 一部失敗した場合、失敗した分だけキューに残り、成功した分だけ送信履歴に入る", async () => {
    createObservation.mockImplementation((report) => {
      if (report.client_event_id === "evt-fail") return Promise.reject(new Error("network error"));
      return Promise.resolve({});
    });
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-ok", shelter_id: "AIT001" }));
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-fail", shelter_id: "AIT002" }));
    });

    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(result.current.pendingReportCount).toBe(1);
    expect(readPendingReportsFromLocalStorage().map((r) => r.client_event_id)).toEqual(["evt-fail"]);

    const history = getSentReportHistory();
    expect(history).toHaveLength(1);
    expect(history[0]).toMatchObject({ shelterId: "AIT001" });
  });

  it("重複防止: 送信に成功した報告は、再度sendPendingReportsを呼んでも二重送信されない", async () => {
    createObservation.mockResolvedValue({});
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-1" }));
    });

    await act(async () => {
      await result.current.sendPendingReports();
    });
    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(createObservation).toHaveBeenCalledTimes(1);
    expect(getSentReportHistory()).toHaveLength(1);
  });

  it("重複防止(冪等性): 再送時もclient_event_idを元の値のまま送る(サーバー側のON CONFLICT DO NOTHINGによる重複排除が効くように)", async () => {
    createObservation.mockRejectedValueOnce(new Error("network error")).mockResolvedValueOnce({});
    const { result } = renderHook(() => useOfflineReportQueue());

    act(() => {
      result.current.addReportToPendingQueue(makeReport({ client_event_id: "evt-stable" }));
    });

    await act(async () => {
      await result.current.sendPendingReports();
    });
    expect(result.current.pendingReportCount).toBe(1);

    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(createObservation).toHaveBeenCalledTimes(2);
    expect(createObservation.mock.calls[0][0].client_event_id).toBe("evt-stable");
    expect(createObservation.mock.calls[1][0].client_event_id).toBe("evt-stable");
    expect(result.current.pendingReportCount).toBe(0);
  });

  it("sendPendingReports: キューが空の場合は何もしない", async () => {
    const { result } = renderHook(() => useOfflineReportQueue());

    await act(async () => {
      await result.current.sendPendingReports();
    });

    expect(createObservation).not.toHaveBeenCalled();
    expect(result.current.pendingReportCount).toBe(0);
  });
});
