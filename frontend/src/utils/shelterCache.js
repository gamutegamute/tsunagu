import { loadJson } from "./localJson.js";
import { STORAGE_KEYS } from "./storageKeys.js";

function isShelter(value) {
  return value
    && typeof value.id === "string"
    && value.id.length > 0
    && typeof value.name === "string"
    && value.name.length > 0;
}

export function loadCachedShelters() {
  const shelters = loadJson(STORAGE_KEYS.cachedShelters, []);
  return Array.isArray(shelters) ? shelters.filter(isShelter) : [];
}

export function saveCachedShelters(shelters) {
  const validShelters = Array.isArray(shelters) ? shelters.filter(isShelter) : [];
  if (validShelters.length > 0) {
    localStorage.setItem(STORAGE_KEYS.cachedShelters, JSON.stringify(validShelters));
  }
}
