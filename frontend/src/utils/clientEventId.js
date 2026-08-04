export function createClientEventId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const random = Math.random().toString(16).slice(2);
  return `web-${Date.now()}-${random}`;
}
