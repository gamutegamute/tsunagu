import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIncidents } from "./useIncidents.js";
import { fetchIncidents } from "../api.js";

vi.mock("../api.js", () => ({
  fetchIncidents: vi.fn(),
}));

function makeApiIncident(overrides = {}) {
  return {
    id: "OBS-001",
    shelter: { id: "AIT001", name: "Shelter A", location: "", created_at: "2026-07-01T00:00:00Z" },
    urgency: "WARNING",
    memo: "水が不足しています",
    observed_at: "2026-07-15T00:00:00Z",
    state: {
      confirm_status: "UNCONFIRMED",
      confirmed_by: null,
      confirmed_at: null,
      confirm_memo: null,
      resolution_request_memo: null,
      resolution_request_staff_name: null,
      resolution_request_active_shelter_id: null,
      resolution_request_at: null,
      resolution_memo: null,
      resolution_staff_name: null,
      resolution_approver_name: null,
      resolution_approved_at: null,
    },
    ...overrides,
  };
}

describe("useIncidents(決定事項34-a/34-b: GET /api/incidentsから直接取得)", () => {
  beforeEach(() => {
    fetchIncidents.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("マウント時にGET /api/incidentsを取得し、正規化して返す", async () => {
    fetchIncidents.mockResolvedValue([makeApiIncident()]);

    const { result } = renderHook(() => useIncidents());

    await waitFor(() => expect(result.current.incidents).toHaveLength(1));
    expect(result.current.incidents[0].id).toBe("OBS-001");
    expect(result.current.incidents[0].shelter.id).toBe("AIT001");
  });

  it("同じ避難所の複数インシデントが両方とも一覧に含まれる(決定事項34-aの直接検証)", async () => {
    fetchIncidents.mockResolvedValue([
      makeApiIncident({ id: "OBS-001", memo: "1件目のインシデント", observed_at: "2026-07-15T02:00:00Z" }),
      makeApiIncident({ id: "OBS-002", memo: "2件目のインシデント(同じ避難所)", observed_at: "2026-07-15T01:00:00Z" }),
    ]);

    const { result } = renderHook(() => useIncidents());

    await waitFor(() => expect(result.current.incidents).toHaveLength(2));
    const ids = result.current.incidents.map((incident) => incident.id);
    expect(ids).toEqual(["OBS-001", "OBS-002"]);
  });

  it("refresh()を呼ぶと再取得する", async () => {
    fetchIncidents.mockResolvedValue([]);
    const { result } = renderHook(() => useIncidents());
    await waitFor(() => expect(fetchIncidents).toHaveBeenCalledTimes(1));

    fetchIncidents.mockResolvedValue([makeApiIncident()]);
    await act(async () => {
      await result.current.refresh();
    });

    expect(fetchIncidents).toHaveBeenCalledTimes(2);
    expect(result.current.incidents).toHaveLength(1);
  });

  it("取得に失敗した場合は例外を投げず、一覧はそのまま(クラッシュしない)", async () => {
    fetchIncidents.mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useIncidents());

    await waitFor(() => expect(fetchIncidents).toHaveBeenCalledTimes(1));
    expect(result.current.incidents).toEqual([]);
  });
});
