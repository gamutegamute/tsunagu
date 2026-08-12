import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

const DATABASE_NAME = "tsunagu-offline";
const DATABASE_VERSION = 1;
const STORE_NAME = "pendingReports";

let databasePromise;
let indexedDbUnavailable = false;

function hasIndexedDb() {
  return !indexedDbUnavailable && typeof indexedDB !== "undefined";
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
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.onerror = () => reject(transaction.error);
    });
  });
}

function readLegacyReports() {
  return loadJson(STORAGE_KEYS.pendingReports, []);
}

function saveLegacyReports(reports) {
  localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify(reports));
}

async function migrateLegacyReports() {
  if (!hasIndexedDb() || localStorage.getItem(STORAGE_KEYS.pendingReportsMigrated) === "true") return;

  const reports = readLegacyReports().filter((report) => report.client_event_id);
  for (const report of reports) {
    await runTransaction("readwrite", (store) => store.put(report));
  }
  localStorage.setItem(STORAGE_KEYS.pendingReportsMigrated, "true");
}

/**
 * 未送信報告を、長期間のオフライン利用に強い IndexedDB から取得する。
 * IndexedDB を使えないブラウザでは従来の localStorage に安全にフォールバックする。
 */
export async function getPendingReports() {
  if (!hasIndexedDb()) return readLegacyReports();

  try {
    await migrateLegacyReports();
    const reports = await runTransaction("readonly", (store) => store.getAll());
    return reports ?? [];
  } catch {
    indexedDbUnavailable = true;
    return readLegacyReports();
  }
}

export async function addPendingReport(report) {
  if (!report.client_event_id) {
    throw new Error("client_event_id is required for an offline report");
  }

  if (!hasIndexedDb()) {
    const reports = readLegacyReports();
    const index = reports.findIndex((item) => item.client_event_id === report.client_event_id);
    if (index >= 0) reports[index] = report;
    else reports.push(report);
    saveLegacyReports(reports);
    return;
  }

  try {
    await migrateLegacyReports();
    await runTransaction("readwrite", (store) => store.put(report));
  } catch {
    indexedDbUnavailable = true;
    await addPendingReport(report);
  }
}

export async function removePendingReport(clientEventId) {
  if (!hasIndexedDb()) {
    saveLegacyReports(readLegacyReports().filter((report) => report.client_event_id !== clientEventId));
    return;
  }

  try {
    await migrateLegacyReports();
    await runTransaction("readwrite", (store) => store.delete(clientEventId));
  } catch {
    indexedDbUnavailable = true;
    await removePendingReport(clientEventId);
  }
}

export async function getPendingReportCount() {
  if (!hasIndexedDb()) return readLegacyReports().length;

  try {
    await migrateLegacyReports();
    return (await runTransaction("readonly", (store) => store.count())) ?? 0;
  } catch {
    indexedDbUnavailable = true;
    return readLegacyReports().length;
  }
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
