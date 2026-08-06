import { describe, expect, it } from "vitest";
import { mergeHistoryEntries } from "./historyEntries.js";

describe("mergeHistoryEntries(送信済み履歴と保留キューのマージ)", () => {
  it("sentReportHistoryのエントリにはstatus: sentを付与し、フィールド名(camelCase)を保つ", () => {
    const sentHistory = [
      { shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:00:00.000Z", sentAt: "2026-08-06T01:00:05.000Z" },
    ];

    const merged = mergeHistoryEntries(sentHistory, []);

    expect(merged).toEqual([
      { key: expect.any(String), shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:00:00.000Z", status: "sent" },
    ]);
  });

  it("pendingReportsのエントリはsnake_caseからcamelCaseへ正規化し、status: unsyncedを付与する", () => {
    const pendingReports = [
      { shelter_id: "AIT002", urgency: "ALERT", observed_at: "2026-08-06T02:00:00.000Z", client_event_id: "evt-1" },
    ];

    const merged = mergeHistoryEntries([], pendingReports);

    expect(merged).toEqual([
      { key: expect.any(String), shelterId: "AIT002", urgency: "ALERT", observedAt: "2026-08-06T02:00:00.000Z", status: "unsynced" },
    ]);
  });

  it("shelter_idがない場合はshelter_codeにフォールバックする(既存のsendPendingReportsと同じ挙動)", () => {
    const pendingReports = [{ shelter_code: "AIT003", urgency: "WARNING", observed_at: "2026-08-06T02:30:00.000Z" }];

    const merged = mergeHistoryEntries([], pendingReports);

    expect(merged[0].shelterId).toBe("AIT003");
  });

  it("送信済み・未同期を混在させ、observedAtの新しい順にソートする", () => {
    const sentHistory = [
      { shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:00:00.000Z", sentAt: "2026-08-06T01:00:05.000Z" },
    ];
    const pendingReports = [
      { shelter_id: "AIT002", urgency: "ALERT", observed_at: "2026-08-06T03:00:00.000Z", client_event_id: "evt-1" },
    ];

    const merged = mergeHistoryEntries(sentHistory, pendingReports);

    expect(merged.map((entry) => entry.shelterId)).toEqual(["AIT002", "AIT001"]);
    expect(merged.map((entry) => entry.status)).toEqual(["unsynced", "sent"]);
  });

  it("双方が空の場合は空配列を返す", () => {
    expect(mergeHistoryEntries([], [])).toEqual([]);
  });
});
