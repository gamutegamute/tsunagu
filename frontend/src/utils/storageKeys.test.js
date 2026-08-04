import { beforeEach, describe, expect, it, vi } from "vitest";

describe("TSUNAGUへのストレージキー移行", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("改名前の未送信キューを新しいキーへ引き継ぐ", async () => {
    const pendingReports = JSON.stringify([{ client_event_id: "offline-report-1" }]);
    localStorage.setItem("shelteros.pendingReports", pendingReports);

    const { STORAGE_KEYS } = await import("./storageKeys.js");

    expect(STORAGE_KEYS.pendingReports).toBe("tsunagu.pendingReports");
    expect(localStorage.getItem(STORAGE_KEYS.pendingReports)).toBe(pendingReports);
  });

  it("新しいキーにデータがあれば旧データで上書きしない", async () => {
    localStorage.setItem("shelteros.reporterName", "旧名称");
    localStorage.setItem("tsunagu.reporterName", "新名称");

    const { STORAGE_KEYS } = await import("./storageKeys.js");

    expect(localStorage.getItem(STORAGE_KEYS.reporterName)).toBe("新名称");
  });
});
