import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchShelters } from "../api.js";
import { useShelterList } from "./useShelterList.js";

vi.mock("../api.js", () => ({
  fetchShelters: vi.fn(),
}));

describe("useShelterList", () => {
  beforeEach(() => {
    localStorage.clear();
    fetchShelters.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("retries shelter loading when the device comes back online", async () => {
    fetchShelters.mockRejectedValueOnce(new Error("offline"));
    fetchShelters.mockResolvedValueOnce([
      { id: "AIT001", name: "Shelter A" },
      { id: "AIT002", name: "Shelter B" },
      { id: "AIT003", name: "Shelter C" },
    ]);

    const { result } = renderHook(() => useShelterList());

    await waitFor(() => expect(fetchShelters).toHaveBeenCalledTimes(1));
    expect(result.current).toEqual([{ id: "AIT001", name: "体育館" }]);

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(result.current).toHaveLength(3));
    expect(result.current.map((shelter) => shelter.id)).toEqual(["AIT001", "AIT002", "AIT003"]);
  });
});
