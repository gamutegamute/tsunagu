/**
 * EmergencyPacket(避難所ID・時刻・人数・水在庫・状態・要請コードのみ)を、
 * 通常のShelterCardに渡せる shelterStatus の形に変換する。
 * 報告者名・メモはEmergency Packetの仕様上そもそも含まれないため、
 * source を "emergency_packet" にしてShelterCard側の注記表示に委ねる。
 */
function packetToShelterStatus(packet, shelterName) {
  return {
    shelter: { id: packet.shelter_id ?? packet.shelter_code, name: shelterName ?? packet.shelter_code },
    latest_observation: {
      people_count: packet.people_count,
      water_stock: packet.water_stock,
      observed_at: packet.received_at,
      source: "emergency_packet",
    },
    status: packet.status,
    request_code: packet.request_code && packet.request_code !== "NONE" ? packet.request_code : null,
  };
}

/**
 * 本部ダッシュボードの状況一覧に、Emergency Packet由来のデータを混ぜ込む。
 *
 * shelter_idが解決できたEmergency Packetは、バックエンドが自動的にobservationとして
 * 同期し既に dashboardItems 側に反映されているため、二重表示しないよう除外する。
 * shelter_idが解決できなかった(未登録の避難所コード等)Emergency Packetだけを、
 * 通常の避難所と同じ shelter-grid に追加のカードとして表示する。
 */
export function mergeEmergencyDataIntoDashboard(dashboardItems, emergencyPackets, shelters) {
  const byShelterId = new Map(dashboardItems.map((item) => [item.shelter.id, item]));

  for (const packet of emergencyPackets) {
    const shelterId = packet.shelter_id ?? packet.shelter_code;
    if (byShelterId.has(shelterId)) continue;
    const shelterName = shelters.find((shelter) => shelter.id === packet.shelter_id)?.name;
    byShelterId.set(shelterId, packetToShelterStatus(packet, shelterName));
  }

  return Array.from(byShelterId.values());
}
