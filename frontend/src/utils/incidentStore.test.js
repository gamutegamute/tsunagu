import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveResolutionRequest,
  confirmIncident,
  requestResolution,
  resolveIncidentDirectly,
} from "./incidentStore.js";
import {
  approveIncidentResolutionRequest,
  confirmIncident as confirmIncidentApi,
  requestIncidentResolution,
  resolveIncident,
} from "../api.js";

vi.mock("../api.js", () => ({
  confirmIncident: vi.fn(),
  resolveIncident: vi.fn(),
  requestIncidentResolution: vi.fn(),
  approveIncidentResolutionRequest: vi.fn(),
}));

describe("incidentStore.js(決定事項34-a/34-b: API呼び出しへの薄いラッパー)", () => {
  beforeEach(() => {
    confirmIncidentApi.mockReset().mockResolvedValue({ id: "OBS-001" });
    resolveIncident.mockReset().mockResolvedValue({ id: "OBS-001" });
    requestIncidentResolution.mockReset().mockResolvedValue({ id: "OBS-001" });
    approveIncidentResolutionRequest.mockReset().mockResolvedValue({ id: "OBS-001" });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("confirmIncident: 確認済みAPIをapproverName/memoで呼ぶ", async () => {
    await confirmIncident("OBS-001", { approverName: "本部 太郎", memo: "確認済み" });

    expect(confirmIncidentApi).toHaveBeenCalledWith("OBS-001", { approverName: "本部 太郎", memo: "確認済み" });
  });

  it("resolveIncidentDirectly: 対応済みAPIをapproverName/staffName/memoで呼ぶ", async () => {
    await resolveIncidentDirectly("OBS-001", { approverName: "本部 太郎", staffName: "現場 次郎", memo: "給水完了" });

    expect(resolveIncident).toHaveBeenCalledWith("OBS-001", {
      approverName: "本部 太郎",
      staffName: "現場 次郎",
      memo: "給水完了",
    });
  });

  it("requestResolution: 申請APIをstaffName/memo/activeShelterIdで呼ぶ(targetShelterIdは送らない)", async () => {
    await requestResolution("OBS-001", {
      memo: "対応完了しました",
      staffName: "現場 三郎",
      targetShelterId: "AIT001",
      activeShelterId: "AIT002",
    });

    expect(requestIncidentResolution).toHaveBeenCalledWith("OBS-001", {
      staffName: "現場 三郎",
      memo: "対応完了しました",
      activeShelterId: "AIT002",
    });
  });

  it("approveResolutionRequest: 承認APIをapproverNameで呼ぶ", async () => {
    await approveResolutionRequest("OBS-001", { approverName: "本部 太郎" });

    expect(approveIncidentResolutionRequest).toHaveBeenCalledWith("OBS-001", { approverName: "本部 太郎" });
  });

  it("各関数はAPIレスポンスをそのまま返す", async () => {
    confirmIncidentApi.mockResolvedValue({ id: "OBS-001", state: { confirm_status: "CONFIRMED" } });

    const result = await confirmIncident("OBS-001", { approverName: "本部 太郎", memo: "" });

    expect(result).toEqual({ id: "OBS-001", state: { confirm_status: "CONFIRMED" } });
  });
});
