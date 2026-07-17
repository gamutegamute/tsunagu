// ---------------------------------------------------------------------------
// バックエンド(backend/app/main.py)と通信する層。
// vite.config.js の server.proxy 設定により、開発中は /api/* が
// http://localhost:8000 のFastAPIサーバーへ転送される。
// (元のApp.jsx内 api() ヘルパーをそのまま移動し、呼び出し箇所ごとに
//  名前付き関数として整理しただけで、通信の中身は変えていない)
// ---------------------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export function fetchShelters() {
  return api("/api/shelters");
}

export function fetchDashboard() {
  return api("/api/dashboard");
}

export function fetchEmergencyPackets() {
  return api("/api/emergency-packets");
}

export function createObservation(payload) {
  return api("/api/observations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createShelter(payload) {
  return api("/api/shelters", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
