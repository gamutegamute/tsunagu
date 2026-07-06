const queueKey = "shelteros.pendingReports";
const cachedDashboardKey = "shelteros.cachedDashboard";

const elements = {
  networkState: document.querySelector("#networkState"),
  shelterId: document.querySelector("#shelterId"),
  reportForm: document.querySelector("#reportForm"),
  peopleCount: document.querySelector("#peopleCount"),
  waterStock: document.querySelector("#waterStock"),
  urgency: document.querySelector("#urgency"),
  memo: document.querySelector("#memo"),
  dashboard: document.querySelector("#dashboard"),
  summary: document.querySelector("#summary"),
  packets: document.querySelector("#packets"),
  syncButton: document.querySelector("#syncButton"),
};

function loadQueue() {
  return JSON.parse(localStorage.getItem(queueKey) || "[]");
}

function saveQueue(queue) {
  localStorage.setItem(queueKey, JSON.stringify(queue));
}

function setNetworkState() {
  const pending = loadQueue().length;
  elements.networkState.textContent = `${navigator.onLine ? "Online" : "Offline"} | ${pending} pending`;
}

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

async function loadShelters() {
  const shelters = await api("/api/shelters");
  elements.shelterId.innerHTML = shelters
    .map((shelter) => `<option value="${shelter.id}">${shelter.id} - ${shelter.name}</option>`)
    .join("");
}

function statusClass(status) {
  return status.toLowerCase();
}

function renderDashboard(items) {
  localStorage.setItem(cachedDashboardKey, JSON.stringify(items));

  const totals = items.reduce(
    (acc, item) => {
      const observation = item.latest_observation;
      acc.people += observation?.people_count || 0;
      acc.water += observation?.water_stock || 0;
      acc[item.status.toLowerCase()] += 1;
      return acc;
    },
    { people: 0, water: 0, normal: 0, warning: 0, alert: 0, unknown: 0 },
  );

  elements.summary.innerHTML = `
    <div class="metric"><strong>${totals.people}</strong><span>Total people</span></div>
    <div class="metric"><strong>${totals.water}</strong><span>Total water</span></div>
    <div class="metric"><strong>${totals.warning}</strong><span>Warnings</span></div>
    <div class="metric"><strong>${totals.alert + totals.unknown}</strong><span>Alerts / unknown</span></div>
  `;

  elements.dashboard.innerHTML = items
    .map((item) => {
      const observation = item.latest_observation;
      const status = statusClass(item.status);
      const observedAt = observation ? new Date(observation.observed_at).toLocaleString() : "No report";
      return `
        <article class="shelter-card ${status}">
          <div class="card-title">
            <h3>${item.shelter.id} ${item.shelter.name}</h3>
            <span class="badge ${status}">${item.status}</span>
          </div>
          <div class="facts">
            <div class="fact"><strong>${observation?.people_count ?? "-"}</strong><span>People</span></div>
            <div class="fact"><strong>${observation?.water_stock ?? "-"}</strong><span>Water</span></div>
          </div>
          <p class="memo">${observation?.memo || item.request_code || "No request"}</p>
          <p class="timestamp">${observedAt}</p>
        </article>
      `;
    })
    .join("");
}

async function loadDashboard() {
  try {
    const items = await api("/api/dashboard");
    renderDashboard(items);
    const packets = await api("/api/emergency-packets");
    elements.packets.textContent = JSON.stringify(packets, null, 2);
  } catch (error) {
    const cached = JSON.parse(localStorage.getItem(cachedDashboardKey) || "[]");
    renderDashboard(cached);
    elements.packets.textContent = "Offline. Showing cached dashboard data.";
  }
}

async function syncQueue() {
  const queue = loadQueue();
  const remaining = [];
  for (const report of queue) {
    try {
      await api("/api/observations", {
        method: "POST",
        body: JSON.stringify(report),
      });
    } catch (error) {
      remaining.push(report);
    }
  }
  saveQueue(remaining);
  setNetworkState();
  await loadDashboard();
}

function createReport() {
  return {
    shelter_id: elements.shelterId.value,
    client_event_id: crypto.randomUUID(),
    people_count: Number(elements.peopleCount.value),
    water_stock: Number(elements.waterStock.value),
    urgency: elements.urgency.value,
    memo: elements.memo.value,
    observed_at: new Date().toISOString(),
  };
}

elements.reportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const report = createReport();
  const queue = loadQueue();

  try {
    await api("/api/observations", {
      method: "POST",
      body: JSON.stringify(report),
    });
  } catch (error) {
    queue.push(report);
    saveQueue(queue);
  }

  elements.memo.value = "";
  setNetworkState();
  await loadDashboard();
});

elements.syncButton.addEventListener("click", syncQueue);
window.addEventListener("online", syncQueue);
window.addEventListener("offline", setNetworkState);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/service-worker.js");
}

setNetworkState();
await loadShelters().catch(() => {
  elements.shelterId.innerHTML = `<option value="AIT001">AIT001 - Shelter A</option>`;
});
await syncQueue();
await loadDashboard();
