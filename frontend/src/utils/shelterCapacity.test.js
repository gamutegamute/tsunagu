import { describe, expect, it } from "vitest";
import { getShelterCapacity } from "./shelterCapacity.js";

describe("getShelterCapacity(決定事項34-b: GET /api/dashboardのshelter.capacityから読み取る)", () => {
  it("shelter.capacityが設定されていれば、その値を返す", () => {
    expect(getShelterCapacity({ id: "AIT001", capacity: 170 })).toBe(170);
  });

  it("shelter.capacityがnullの場合はnullを返す", () => {
    expect(getShelterCapacity({ id: "AIT001", capacity: null })).toBeNull();
  });

  it("shelterそのものがnull/undefinedでもクラッシュせずnullを返す", () => {
    expect(getShelterCapacity(null)).toBeNull();
    expect(getShelterCapacity(undefined)).toBeNull();
  });
});
