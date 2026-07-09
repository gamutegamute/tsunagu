import { useEffect, useMemo, useState } from "react";

const queueKey = "shelteros.pendingReports";
const cachedDashboardKey = "shelteros.cachedDashboard";
const reporterNameKey = "shelteros.reporterName";

const initialReport = {
  reporter_name: "",
  shelter_id: "",
  people_count: 50,
  water_stock: 20,
  urgency: "NORMAL",
  memo: "",
};

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function loadQueue() {
  return loadJson(queueKey, []);
}

function saveQueue(queue) {
  localStorage.setItem(queueKey, JSON.stringify(queue));
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

function statusClass(status) {
  return status.toLowerCase();
}

function buildEmergencyPacket(report, status, requestCode) {
  const observedAt = new Date(report.observed_at);
  const time = observedAt.toTimeString().slice(0, 5);
  return `v1|${report.shelter_id}|${time}|${report.people_count}|${report.water_stock}|${status}|${requestCode || "REQ_CONFIRM"}`;
}

function decideLocalStatus(report) {
  if (report.urgency === "CRITICAL") return "ALERT";
  if (report.urgency === "HIGH" || report.water_stock < 20) return "WARNING";
  return "NORMAL";
}

function decideLocalRequestCode(report, status) {
  if (report.water_stock < 20) return "REQ_WATER";
  if (status === "ALERT") return "REQ_CONFIRM";
  return null;
}

function App() {
  const [networkMode, setNetworkMode] = useState(navigator.onLine ? "normal" : "offline");
  const [shelters, setShelters] = useState([]);
  const [dashboardItems, setDashboardItems] = useState(loadJson(cachedDashboardKey, []));
  const [packets, setPackets] = useState([]);
  const [lastPacket, setLastPacket] = useState("");
  const [pendingCount, setPendingCount] = useState(loadQueue().length);
  const [report, setReport] = useState({
    ...initialReport,
    reporter_name: localStorage.getItem(reporterNameKey) || "",
  });

  const isOnline = networkMode === "normal";
  const isEmergency = networkMode === "emergency";

  const modeLabel = useMemo(() => {
    if (networkMode === "emergency") return "非常時";
    if (networkMode === "offline") return "オフライン";
    return "オンライン";
  }, [networkMode]);

  async function loadShelters() {
    const items = await api("/api/shelters");
    setShelters(items);
    setReport((current) => ({
      ...current,
      shelter_id: current.shelter_id || items[0]?.id || "AIT001",
    }));
  }

  function renderCachedDashboard(items) {
    localStorage.setItem(cachedDashboardKey, JSON.stringify(items));
    setDashboardItems(items);
  }

  async function loadDashboard() {
    try {
      const items = await api("/api/dashboard");
      renderCachedDashboard(items);
      setPackets(await api("/api/emergency-packets"));
    } catch {
      renderCachedDashboard(loadJson(cachedDashboardKey, []));
    }
  }

  async function syncQueue() {
    const queue = loadQueue();
    const remaining = [];
    for (const queuedReport of queue) {
      try {
        await api("/api/observations", {
          method: "POST",
          body: JSON.stringify(queuedReport),
        });
      } catch {
        remaining.push(queuedReport);
      }
    }
    saveQueue(remaining);
    setPendingCount(remaining.length);
    await loadDashboard();
  }

  useEffect(() => {
    loadShelters().catch(() => {
      setShelters([{ id: "AIT001", name: "体育館" }]);
      setReport((current) => ({ ...current, shelter_id: current.shelter_id || "AIT001" }));
    });
    loadDashboard();

    const handleOnline = () => {
      setNetworkMode("normal");
      syncQueue();
    };
    const handleOffline = () => setNetworkMode("offline");

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/service-worker.js");
    }

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  function updateReport(field, value) {
    setReport((current) => ({ ...current, [field]: value }));
  }

  function createReportPayload() {
    const trimmedReporterName = report.reporter_name.trim();
    if (trimmedReporterName) {
      localStorage.setItem(reporterNameKey, trimmedReporterName);
    }

    const payload = {
      reporter_name: trimmedReporterName,
      shelter_id: report.shelter_id,
      client_event_id: crypto.randomUUID(),
      people_count: Number(report.people_count),
      water_stock: Number(report.water_stock),
      urgency: report.urgency,
      memo: report.memo,
      observed_at: new Date().toISOString(),
      source: networkMode === "offline" || networkMode === "emergency" ? "offline" : "web",
    };

    return payload;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const payload = createReportPayload();

    if (isOnline) {
      try {
        await api("/api/observations", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      } catch {
        const queue = [...loadQueue(), payload];
        saveQueue(queue);
        setPendingCount(queue.length);
      }
    } else {
      const queue = [...loadQueue(), payload];
      saveQueue(queue);
      setPendingCount(queue.length);

      if (isEmergency) {
        const status = decideLocalStatus(payload);
        setLastPacket(buildEmergencyPacket(payload, status, decideLocalRequestCode(payload, status)));
      }
    }

    updateReport("memo", "");
    await loadDashboard();
  }

  const totals = dashboardItems.reduce(
    (acc, item) => {
      const observation = item.latest_observation;
      acc.people += observation?.people_count || 0;
      acc.water += observation?.water_stock || 0;
      acc[item.status.toLowerCase()] += 1;
      return acc;
    },
    { people: 0, water: 0, normal: 0, warning: 0, alert: 0, unknown: 0 },
  );

  return (
    <>
      <header className="topbar">
        <div>
          <h1>ShelterOS</h1>
          <p>通信が途絶えても、現場の状況は途絶えない。</p>
        </div>
        <div className="mode-controls" aria-label="通信状態">
          {["normal", "offline", "emergency"].map((mode) => (
            <button
              className={networkMode === mode ? "mode-button active" : "mode-button"}
              key={mode}
              onClick={() => setNetworkMode(mode)}
              type="button"
            >
              {mode === "normal" ? "通常" : mode === "offline" ? "オフライン" : "非常時"}
            </button>
          ))}
        </div>
      </header>

      <main className="layout">
        <section className="panel report-panel">
          <div className="section-title">
            <h2>現場報告</h2>
            <span className={`network ${networkMode}`}>{modeLabel}</span>
          </div>

          {networkMode === "offline" && (
            <div className="status-hero offline">
              <strong>オフライン — 通信復旧を待っています</strong>
              <span>報告は端末に保存され、回線復帰後に自動で同期されます。</span>
            </div>
          )}

          {networkMode === "emergency" && (
            <div className="status-hero emergency">
              <strong>非常時 — LoRa非常用通信で稼働中</strong>
              <span>詳細データは端末に保存し、最低限の情報だけ送信します。</span>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <label>
              報告者名
              <input
                onChange={(event) => updateReport("reporter_name", event.target.value)}
                placeholder="田中"
                required
                value={report.reporter_name}
              />
            </label>
            <label>
              避難所
              <select
                onChange={(event) => updateReport("shelter_id", event.target.value)}
                required
                value={report.shelter_id}
              >
                {shelters.map((shelter) => (
                  <option key={shelter.id} value={shelter.id}>
                    {shelter.id} - {shelter.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="split">
              <label>
                人数
                <input
                  min="0"
                  onChange={(event) => updateReport("people_count", event.target.value)}
                  required
                  type="number"
                  value={report.people_count}
                />
              </label>
              <label>
                水
                <input
                  min="0"
                  onChange={(event) => updateReport("water_stock", event.target.value)}
                  required
                  type="number"
                  value={report.water_stock}
                />
              </label>
            </div>
            <fieldset>
              <legend>緊急度</legend>
              <div className="urgency-grid">
                {["NORMAL", "HIGH", "CRITICAL"].map((urgency) => (
                  <button
                    className={report.urgency === urgency ? `urgency active ${urgency.toLowerCase()}` : "urgency"}
                    key={urgency}
                    onClick={() => updateReport("urgency", urgency)}
                    type="button"
                  >
                    {urgency}
                  </button>
                ))}
              </div>
            </fieldset>
            <label>
              メモ
              <textarea
                onChange={(event) => updateReport("memo", event.target.value)}
                placeholder="気づいたことを自由に記入してください"
                rows="3"
                value={report.memo}
              />
            </label>
            <p className="pending">未送信 {pendingCount}件</p>
            <button type="submit">報告する</button>
          </form>
        </section>

        <section className="panel dashboard-panel">
          <div className="section-title">
            <h2>本部ダッシュボード</h2>
            <button id="syncButton" onClick={syncQueue} type="button">
              同期
            </button>
          </div>
          <div className="summary">
            <div className="metric"><strong>{totals.people}</strong><span>合計人数</span></div>
            <div className="metric"><strong>{totals.water}</strong><span>水在庫</span></div>
            <div className="metric"><strong>{totals.warning}</strong><span>注意</span></div>
            <div className="metric"><strong>{totals.alert + totals.unknown}</strong><span>警戒/不明</span></div>
          </div>
          <div className="shelter-grid">
            {dashboardItems.map((item) => {
              const observation = item.latest_observation;
              const status = statusClass(item.status);
              return (
                <article className={`shelter-card ${status}`} key={item.shelter.id}>
                  <div className="card-title">
                    <h3>{item.shelter.id} {item.shelter.name}</h3>
                    <span className={`badge ${status}`}>{item.status}</span>
                  </div>
                  <div className="facts">
                    <div className="fact"><strong>{observation?.people_count ?? "-"}</strong><span>人数</span></div>
                    <div className="fact"><strong>{observation?.water_stock ?? "-"}</strong><span>水</span></div>
                  </div>
                  {observation && (
                    <p className="reporter">
                      {observation.source === "emergency_packet"
                        ? "📡 LoRaパケット"
                        : `👤 報告者: ${observation.reporter_name || "不明"}`}
                    </p>
                  )}
                  <p className="memo">{observation?.memo || item.request_code || "要請なし"}</p>
                  <p className="timestamp">
                    {observation ? new Date(observation.observed_at).toLocaleString() : "報告なし"}
                  </p>
                </article>
              );
            })}
          </div>
        </section>

        <section className="panel packets-panel">
          <h2>非常時の最低限情報</h2>
          {lastPacket && <pre>{lastPacket}</pre>}
          {!lastPacket && <pre>{JSON.stringify(packets, null, 2) || "送信履歴はまだありません。"}</pre>}
        </section>
      </main>
    </>
  );
}

export default App;
