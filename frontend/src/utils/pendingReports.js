import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

const DATABASE_NAME = "tsunagu-offline";
const DATABASE_VERSION = 1;
const STORE_NAME = "pendingReports";
const LOCK_NAME = "tsunagu-pending-reports";
const FALLBACK_PREFIX = `${STORAGE_KEYS.pendingReportsFallback}.report.`;

let databasePromise;
let indexedDbUnavailable = false;
let storeOperation = Promise.resolve();

// Serialize migrations and mutations so a late migration cannot restore a deleted row.
function serialize(operation) {
  const result = storeOperation.then(() => navigator.locks?.request
    ? navigator.locks.request(LOCK_NAME, operation)
    : operation());
  storeOperation = result.catch(() => {});
  return result;
}

function hasIndexedDb() {
  return typeof indexedDB !== "undefined";
}

export class PendingReportsReadError extends Error {
  constructor(reports, cause) {
    super("未送信報告の全件を読み出せません。端末内の報告は保持されています。", { cause });
    this.reports = reports;
  }
}

function reconnectOnNextRead() {
  indexedDbUnavailable = true;
  const previous = databasePromise;
  databasePromise = undefined;
  void previous?.then((database) => database?.close()).catch(() => {});
}

function openDatabase() {
  if (!hasIndexedDb()) return Promise.resolve(null);
  if (databasePromise) return databasePromise;

  databasePromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "client_event_id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      indexedDbUnavailable = true;
      databasePromise = undefined;
      reject(request.error);
    };
  });

  return databasePromise;
}

function runTransaction(mode, operation) {
  return openDatabase().then((database) => {
    if (!database) return null;
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const store = transaction.objectStore(STORE_NAME);
      const request = operation(store);
      let result;
      request.onsuccess = () => { result = request.result; };
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || new Error("IndexedDB transaction aborted"));
      transaction.oncomplete = () => resolve(result);
    });
  });
}

function readLegacyReports() {
  return loadJson(STORAGE_KEYS.pendingReports, []);
}

async function migrateLegacyReports() {
  if (!hasIndexedDb() || localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated) === "true") return;

  const reports = readLegacyReports().filter((report) => report.client_event_id);
  for (const report of reports) {
    await runTransaction("readwrite", (store) => store.put(report));
  }
  localStorage.setItem(STORAGE_KEYS.pendingReportsMigrated, "true");
  localStorage.removeItem(STORAGE_KEYS.pendingReports);
}

// This journal is separate from the already-migrated legacy queue. Null entries
// are durable deletions when IndexedDB is temporarily unavailable.
function readFallback() {
  const reports = { ...loadJson(STORAGE_KEYS.pendingReportsFallback, {}) };
  for (const key of fallbackKeys()) {
    const entry = loadJson(key, null);
    if (entry) reports[entry.id] = entry.report;
  }
  return reports;
}

function fallbackKeys() {
  return Object.keys(localStorage).filter((key) => key.startsWith(FALLBACK_PREFIX));
}

function writeFallback(id, report) {
  // Different reports never overwrite a shared read-modify-write snapshot.
  localStorage.setItem(`${FALLBACK_PREFIX}${encodeURIComponent(id)}`, JSON.stringify({ id, report }));
}

async function reconcileFallback() {
  const legacySnapshot = localStorage.getItem(STORAGE_KEYS.pendingReportsFallback);
  const snapshots = fallbackKeys().map((key) => [key, localStorage.getItem(key)]);
  const entries = Object.entries(readFallback());
  for (const [id, report] of entries) {
    await runTransaction("readwrite", (store) => report === null ? store.delete(id) : store.put(report));
  }
  // Never clear the whole journal: another window may have added a report.
  // Web Locks also serialize recovery/deletion across windows when available.
  for (const [key, value] of snapshots) {
    if (localStorage.getItem(key) === value) localStorage.removeItem(key);
  }
  if (legacySnapshot !== null && localStorage.getItem(STORAGE_KEYS.pendingReportsFallback) === legacySnapshot) {
    localStorage.removeItem(STORAGE_KEYS.pendingReportsFallback);
  }
}

function fallbackReports() {
  const reports = new Map(
    (localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated) === "true" ? [] : readLegacyReports())
      .map((report) => [report.client_event_id, report]),
  );
  for (const [id, report] of Object.entries(readFallback())) {
    if (report === null) reports.delete(id);
    else reports.set(id, report);
  }
  return [...reports.values()];
}

/**
 * 未送信報告を、長期間のオフライン利用に強い IndexedDB から取得する。
 * IndexedDB を使えないブラウザでは従来の localStorage に安全にフォールバックする。
 */
async function readReports() {
  if (!hasIndexedDb()) return fallbackReports();

  try {
    await migrateLegacyReports();
    await reconcileFallback();
    const reports = await runTransaction("readonly", (store) => store.getAll());
    indexedDbUnavailable = false;
    return reports ?? [];
  } catch (error) {
    reconnectOnNextRead();
    throw new PendingReportsReadError(fallbackReports(), error);
  }
}

export function getPendingReports() {
  return serialize(readReports);
}

async function addReport(report) {
  if (!report.client_event_id) {
    throw new Error("client_event_id is required for an offline report");
  }

  if (!hasIndexedDb() || indexedDbUnavailable) {
    writeFallback(report.client_event_id, report);
    return;
  }

  try {
    await migrateLegacyReports();
    await reconcileFallback();
    await runTransaction("readwrite", (store) => store.put(report));
  } catch {
    reconnectOnNextRead();
    writeFallback(report.client_event_id, report);
  }
}

export function addPendingReport(report) {
  return serialize(() => addReport(report));
}

async function removeReport(clientEventId) {
  if (!hasIndexedDb() || indexedDbUnavailable) {
    writeFallback(clientEventId, null);
    return;
  }

  try {
    await migrateLegacyReports();
    await reconcileFallback();
    await runTransaction("readwrite", (store) => store.delete(clientEventId));
  } catch {
    reconnectOnNextRead();
    writeFallback(clientEventId, null);
  }
}

export function removePendingReport(clientEventId) {
  return serialize(() => removeReport(clientEventId));
}

export function getPendingReportCount() {
  return serialize(async () => (await readReports()).length);
}

export async function requestPersistentStorage() {
  if (!navigator.storage?.persist) return false;
  if (await navigator.storage.persisted?.()) return true;
  return navigator.storage.persist();
}

export function resetPendingReportStoreForTests() {
  databasePromise = undefined;
  indexedDbUnavailable = false;
}
