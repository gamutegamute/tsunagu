import { describe, expect, it } from "vitest";
import { mergeEmergencyDataIntoDashboard, packetToShelterStatus } from "./emergencyPacket.js";

const packet = {
  id: "EP-001",
  shelter_code: "AIT999",
  shelter_id: null,
  people_count: 170,
  water_stock: 18,
  status: "WARNING",
  request_code: "REQ_WATER",
  received_at: "2026-07-16T00:00:00Z",
};

describe("Emergency Packetの画面表示用変換", () => {
  it("詳細画面とTimelineで使えるObservation項目を生成する", () => {
    const status = packetToShelterStatus(packet);

    expect(status.shelter).toEqual({ id: "AIT999", name: "AIT999" });
    expect(status.latest_observation).toMatchObject({
      id: "EP-001",
      urgency: "WARNING",
      memo: "",
      reporter_name: "",
      source: "emergency_packet",
    });
  });

  it("未登録避難所のPacketをダッシュボード一覧へ追加する", () => {
    const items = mergeEmergencyDataIntoDashboard([], [packet], []);

    expect(items).toHaveLength(1);
    expect(items[0].shelter.id).toBe("AIT999");
    expect(items[0].latest_observation.id).toBe("EP-001");
  });
});
