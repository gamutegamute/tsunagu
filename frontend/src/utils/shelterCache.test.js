import { beforeEach, describe, expect, it } from "vitest";
import { loadCachedShelters, saveCachedShelters } from "./shelterCache.js";
import { STORAGE_KEYS } from "./storageKeys.js";

describe("shelterCache", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores only shelters that can be displayed in the selector", () => {
    saveCachedShelters([
      { id: "AIT001", name: "Shelter A", location: "Gym" },
      { id: "", name: "Invalid" },
      { id: "AIT002", name: "Shelter B" },
    ]);

    expect(loadCachedShelters()).toEqual([
      { id: "AIT001", name: "Shelter A", location: "Gym" },
      { id: "AIT002", name: "Shelter B" },
    ]);
  });

  it("returns an empty cache when saved data is malformed", () => {
    localStorage.setItem(STORAGE_KEYS.cachedShelters, "not-json");

    expect(loadCachedShelters()).toEqual([]);
  });
});
