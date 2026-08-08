function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find((cookie) => cookie.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
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

  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
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

export const createObservation = (payload) => api("/api/observations", {
  method: "POST",
  body: JSON.stringify(payload),
});

export const createShelter = (payload) => api("/api/shelters", {
  method: "POST",
  body: JSON.stringify(payload),
});

export const updateObservationVerification = (observationId, status) => api(
  `/api/observations/${encodeURIComponent(observationId)}/verification`,
  { method: "PATCH", body: JSON.stringify({ status }) },
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

export const approveIncidentResolutionRequest = (observationId, { approverName }) => api(
  `/api/incidents/${encodeURIComponent(observationId)}/resolution-requests/approve`,
  { method: "POST", body: JSON.stringify({ approver_name: approverName }) },
);
