export function applyDashboardFreshness(item, now = Date.now()) {
  const observation = item.latest_observation;
  const observedAt = Date.parse(observation?.observed_at);
  if (!Number.isFinite(observedAt) || now - observedAt <= 24 * 3600000) return item;
  const derived = observation.water_stock < 20 ? "REQ_WATER" : "REQ_CONFIRM";
  const explicit = item.explicit_request_code ?? null;
  return { ...item, status: "ALERT", derived_request_code: derived, request_code: explicit || derived, is_stale: true };
}
