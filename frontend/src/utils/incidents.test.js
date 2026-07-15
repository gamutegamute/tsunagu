import { describe, expect, it, beforeEach } from "vitest";
import { canRequestResolution, deriveIncidentsFromDashboard } from "./incidents.js";

function makeDashboardItem({ latest_observation: observationOverrides, ...rest } = {}) {
  return {
    shelter: { id: "SH-001", name: "テスト避難所" },
    status: "normal",
    ...rest,
    latest_observation: {
      id: "OBS-001",
      memo: "水が不足しています",
      observed_at: "2026-07-15T00:00:00Z",
      source: "field_report",
      ...observationOverrides,
    },
  };
}

describe("deriveIncidentsFromDashboard", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("メモ入りの現場報告(field_report)をIncidentとして抽出する", () => {
    const items = [makeDashboardItem()];
    const incidents = deriveIncidentsFromDashboard(items);
    expect(incidents).toHaveLength(1);
    expect(incidents[0].id).toBe("OBS-001");
  });

  it("source === 'emergency_packet' の報告はIncidentから除外する", () => {
    const items = [makeDashboardItem({ latest_observation: { source: "emergency_packet" } })];
    const incidents = deriveIncidentsFromDashboard(items);
    expect(incidents).toHaveLength(0);
  });

  it("emergency_packetとfield_reportが混在する場合はfield_reportのみ抽出する", () => {
    const items = [
      makeDashboardItem({ latest_observation: { id: "OBS-EP", source: "emergency_packet" } }),
      makeDashboardItem({ latest_observation: { id: "OBS-FR", source: "field_report" } }),
    ];
    const incidents = deriveIncidentsFromDashboard(items);
    expect(incidents).toHaveLength(1);
    expect(incidents[0].id).toBe("OBS-FR");
  });

  it("メモが空の報告は元々除外される(既存挙動の確認)", () => {
    const items = [makeDashboardItem({ latest_observation: { memo: "" } })];
    const incidents = deriveIncidentsFromDashboard(items);
    expect(incidents).toHaveLength(0);
  });

  it("本部で確認済みでも未解決なら対応済み申請ができる", () => {
    expect(canRequestResolution({ confirmStatus: "CONFIRMED", resolutionRequest: null, resolution: null })).toBe(true);
  });

  it("承認待ちまたは対応済みの場合は重ねて対応済み申請できない", () => {
    expect(canRequestResolution({ resolutionRequest: { memo: "対応済み" }, resolution: null })).toBe(false);
    expect(canRequestResolution({ resolutionRequest: null, resolution: { memo: "対応済み" } })).toBe(false);
  });
});
