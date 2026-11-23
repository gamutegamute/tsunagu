function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find((cookie) => cookie.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

export class ApiError extends Error {
  constructor(status, body, retryAfter = null) {
    super(body?.detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    const seconds = Number(retryAfter);
    this.retryAfterMs = retryAfter === null ? 0 : Number.isFinite(seconds)
      ? Math.max(0, seconds * 1000) : Math.max(0, Date.parse(retryAfter) - Date.now()) || 0;
  }
}

export const API_TIMEOUT_MS = 15000;

export class ApiResponseError extends Error {
  constructor() {
    super("受理結果を確認できませんでした。同じ報告IDで再試行します。");
    this.name = "ApiResponseError";
  }
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = readCookie("tsunagu_csrf");
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }

  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      (async () => {
        const response = await fetch(path, { credentials: "same-origin", ...options, headers, signal: controller.signal });
        let body = null;
        if (response.status !== 204) {
          try { body = await response.json(); }
          catch { if (response.ok) throw new ApiResponseError(); }
        }
        if (!response.ok) throw new ApiError(response.status, body, response.headers.get("Retry-After"));
        return body;
      })(),
      new Promise((_, reject) => {
        timer = window.setTimeout(() => {
          reject(new Error("応答待ちがタイムアウトしました。受理の有無は未確認です。"));
          controller.abort();
        }, API_TIMEOUT_MS);
      }),
    ]);
  } finally { window.clearTimeout(timer); }
}

export const fetchAuthConfig = () => api("/api/auth/config");
export const fetchCurrentUser = () => api("/api/auth/me");
export const devLogin = (role) => api("/api/auth/dev-login", {
  method: "POST",
  body: JSON.stringify({ role, name: role === "hq" ? "ローカル本部職員" : "ローカル現場職員" }),
});
export const logout = () => api("/api/auth/logout", { method: "POST" });

export const fetchShelters = () => api("/api/shelters");
export const fetchDashboard = () => api("/api/dashboard");
export const fetchEmergencyPackets = () => api("/api/emergency-packets");
export const fetchDemoControlStatus = () => api("/api/admin/demo");
export const resetDemoData = (confirmation) => api("/api/admin/demo/reset", {
  method: "POST",
  body: JSON.stringify({ confirmation }),
});

export async function createObservation(payload) {
  const observation = await api("/api/observations", { method: "POST", body: JSON.stringify(payload) });
  if (!observation || typeof observation.id !== "string" || !observation.id
    || observation.client_event_id !== payload.client_event_id
    || observation.shelter_id !== (payload.shelter_id ?? payload.shelter_code)
    || observation.people_count !== payload.people_count || observation.water_stock !== payload.water_stock
    || observation.urgency !== (payload.urgency ?? "NORMAL") || observation.memo !== (payload.memo ?? "")
    || !Number.isFinite(Date.parse(observation.observed_at))) throw new ApiResponseError();
  return observation;
}

export const createShelter = (payload) => api("/api/shelters", {
  method: "POST",
  body: JSON.stringify(payload),
});

export const updateObservationVerification = (observationId, status) => api(
  `/api/observations/${encodeURIComponent(observationId)}/verification`,
  { method: "PATCH", body: JSON.stringify({ status }) },
);

export const fetchShelterObservations = (shelterId) => api(
  `/api/shelters/${encodeURIComponent(shelterId)}/observations`,
);

export const fetchIncidents = () => api("/api/incidents");

export const confirmIncident = (observationId, { approverName, memo }) => api(
  `/api/incidents/${encodeURIComponent(observationId)}/confirm`,
  { method: "POST", body: JSON.stringify({ approver_name: approverName, memo }) },
);

export const resolveIncident = (observationId, { approverName, staffName, memo }) => api(
  `/api/incidents/${encodeURIComponent(observationId)}/resolve`,
  { method: "POST", body: JSON.stringify({ approver_name: approverName, staff_name: staffName, memo }) },
);

export const requestIncidentResolution = (observationId, { staffName, memo, activeShelterId }) => api(
  `/api/incidents/${encodeURIComponent(observationId)}/resolution-requests`,
  { method: "POST", body: JSON.stringify({ staff_name: staffName, memo, active_shelter_id: activeShelterId }) },
);

export const approveIncidentResolutionRequest = (observationId, { approverName, requestVersion }) => api(
  `/api/incidents/${encodeURIComponent(observationId)}/resolution-requests/approve`,
  { method: "POST", body: JSON.stringify({ approver_name: approverName, request_version: requestVersion }) },
);
