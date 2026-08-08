import { describe, expect, it } from "vitest";
import { canRequestResolution, normalizeIncident } from "./incidents.js";

function makeApiIncident(overrides = {}) {
  return {
    id: "OBS-001",
    shelter: { id: "SH-001", name: "テスト避難所", location: "", created_at: "2026-07-01T00:00:00Z" },
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

describe("normalizeIncident(決定事項34-a/34-b: GET /api/incidentsのレスポンスを画面用に正規化)", () => {
  it("基本フィールドをキャメルケースへ変換する", () => {
    const incident = normalizeIncident(makeApiIncident());

    expect(incident.id).toBe("OBS-001");
    expect(incident.shelter).toEqual({ id: "SH-001", name: "テスト避難所", location: "", created_at: "2026-07-01T00:00:00Z" });
    expect(incident.urgency).toBe("WARNING");
    expect(incident.memo).toBe("水が不足しています");
    expect(incident.observedAt).toBe("2026-07-15T00:00:00Z");
  });

  it("確認済み状態のフィールドを変換する", () => {
    const incident = normalizeIncident(
      makeApiIncident({
        state: {
          ...makeApiIncident().state,
          confirm_status: "CONFIRMED",
          confirmed_by: "本部 太郎",
          confirm_memo: "現場に確認済み",
        },
      }),
    );

    expect(incident.confirmStatus).toBe("CONFIRMED");
    expect(incident.confirmedBy).toBe("本部 太郎");
    expect(incident.confirmMemo).toBe("現場に確認済み");
  });

  it("resolution_request_atが無い場合、resolutionRequestはnullになる", () => {
    const incident = normalizeIncident(makeApiIncident());
    expect(incident.resolutionRequest).toBeNull();
  });

  it("対応済み申請中のフィールドを変換し、targetShelterIdはIncidentの避難所を使う", () => {
    const incident = normalizeIncident(
      makeApiIncident({
        state: {
          ...makeApiIncident().state,
          resolution_request_memo: "対応完了しました",
          resolution_request_staff_name: "現場 三郎",
          resolution_request_active_shelter_id: "SH-002",
          resolution_request_at: "2026-07-15T01:00:00Z",
        },
      }),
    );

    expect(incident.resolutionRequest).toEqual({
      memo: "対応完了しました",
      staffName: "現場 三郎",
      targetShelterId: "SH-001",
      activeShelterId: "SH-002",
      requestedAt: "2026-07-15T01:00:00Z",
    });
  });

  it("resolution_approved_atが無い場合、resolutionはnullになる", () => {
    const incident = normalizeIncident(makeApiIncident());
    expect(incident.resolution).toBeNull();
  });

  it("対応済み確定のフィールドを変換する", () => {
    const incident = normalizeIncident(
      makeApiIncident({
        state: {
          ...makeApiIncident().state,
          resolution_memo: "給水対応完了",
          resolution_staff_name: "現場 次郎",
          resolution_approver_name: "本部 太郎",
          resolution_approved_at: "2026-07-15T02:00:00Z",
        },
      }),
    );

    expect(incident.resolution).toEqual({
      memo: "給水対応完了",
      staffName: "現場 次郎",
      approverName: "本部 太郎",
      approvedAt: "2026-07-15T02:00:00Z",
    });
  });
});

describe("canRequestResolution", () => {
  it("本部で確認済みでも未解決なら対応済み申請ができる", () => {
    expect(canRequestResolution({ confirmStatus: "CONFIRMED", resolutionRequest: null, resolution: null })).toBe(true);
  });

  it("承認待ちまたは対応済みの場合は重ねて対応済み申請できない", () => {
    expect(canRequestResolution({ resolutionRequest: { memo: "対応済み" }, resolution: null })).toBe(false);
    expect(canRequestResolution({ resolutionRequest: null, resolution: { memo: "対応済み" } })).toBe(false);
  });
});
