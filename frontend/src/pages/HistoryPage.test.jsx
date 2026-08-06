import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import HistoryPage from "./HistoryPage.jsx";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

vi.mock("../hooks/useShelterList.js", () => ({
  useShelterList: () => [
    { id: "AIT001", name: "Shelter A" },
    { id: "AIT002", name: "Shelter B" },
  ],
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  );
}

describe("HistoryPage(決定事項33-a: デザイン改善)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("送信履歴が0件のとき、空状態メッセージと件数バッジ0件を表示する", () => {
    renderPage();

    expect(screen.getByText("送信履歴はまだありません")).not.toBeNull();
    expect(screen.getByText("0件")).not.toBeNull();
  });

  it("送信履歴がある場合、避難所名・時刻・緊急度を含むカードとして一覧表示する", () => {
    const history = [
      { shelterId: "AIT001", urgency: "WARNING", observedAt: "2026-08-06T01:30:00.000Z", sentAt: "2026-08-06T01:30:05.000Z" },
    ];
    localStorage.setItem(STORAGE_KEYS.sentReportHistory, JSON.stringify(history));

    renderPage();

    expect(screen.getByText("1件")).not.toBeNull();
    expect(screen.getByText("AIT001 Shelter A")).not.toBeNull();
    expect(screen.getByText(/WARNING/)).not.toBeNull();
    expect(document.querySelector(".history-item.warning")).not.toBeNull();
    // 他画面(ShelterCard/IncidentCard)と統一感のあるカード構造(左アクセントバー)になっていること
    expect(document.querySelector(".history-item-accent")).not.toBeNull();
  });

  it("同期状態はアイコン単体に頼らず「送信済み」のテキストラベルを併記する", () => {
    const history = [
      { shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:30:00.000Z", sentAt: "2026-08-06T01:30:05.000Z" },
    ];
    localStorage.setItem(STORAGE_KEYS.sentReportHistory, JSON.stringify(history));

    renderPage();

    expect(screen.getByText("送信済み")).not.toBeNull();
    const sentChip = document.querySelector(".history-sync-chip.sent");
    expect(sentChip).not.toBeNull();
    // テキストだけでなく、アイコン(svg)も併記されていること
    expect(sentChip.querySelector("svg")).not.toBeNull();
  });

  it("送信履歴一覧はpanel/section-titleの共通レイアウトで表示される(他画面との統一感)", () => {
    renderPage();

    expect(document.querySelector(".panel.history-panel")).not.toBeNull();
    expect(document.querySelector(".section-title")).not.toBeNull();
  });

  it("追加対応: 保留キュー(pendingReports)の報告も「未同期」として一覧に含める", () => {
    const sentHistory = [
      { shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:00:00.000Z", sentAt: "2026-08-06T01:00:05.000Z" },
    ];
    const pendingReports = [
      { shelter_id: "AIT002", urgency: "ALERT", observed_at: "2026-08-06T02:00:00.000Z", client_event_id: "evt-1" },
    ];
    localStorage.setItem(STORAGE_KEYS.sentReportHistory, JSON.stringify(sentHistory));
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify(pendingReports));

    renderPage();

    // 送信済み1件 + 未同期1件で合計2件
    expect(screen.getByText("2件")).not.toBeNull();
    expect(screen.getByText("AIT002 Shelter B")).not.toBeNull();
    expect(screen.getByText("未同期")).not.toBeNull();
    expect(document.querySelector(".history-sync-chip.unsynced")).not.toBeNull();
  });

  it("追加対応: 未同期(保留中)の報告のほうが新しい場合、一覧の先頭に表示される(時刻の新しい順)", () => {
    const sentHistory = [
      { shelterId: "AIT001", urgency: "NORMAL", observedAt: "2026-08-06T01:00:00.000Z", sentAt: "2026-08-06T01:00:05.000Z" },
    ];
    const pendingReports = [
      { shelter_id: "AIT002", urgency: "ALERT", observed_at: "2026-08-06T03:00:00.000Z", client_event_id: "evt-1" },
    ];
    localStorage.setItem(STORAGE_KEYS.sentReportHistory, JSON.stringify(sentHistory));
    localStorage.setItem(STORAGE_KEYS.pendingReports, JSON.stringify(pendingReports));

    renderPage();

    const shelterNames = Array.from(document.querySelectorAll(".history-item-shelter")).map((el) => el.textContent);
    expect(shelterNames).toEqual(["AIT002 Shelter B", "AIT001 Shelter A"]);
  });
});
