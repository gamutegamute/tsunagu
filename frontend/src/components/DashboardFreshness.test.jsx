import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import DashboardFreshness from "./DashboardFreshness.jsx";
import ShelterCard from "./ShelterCard.jsx";
import { applyDashboardFreshness } from "../utils/dashboardFreshness.js";
afterEach(cleanup);
it("shows cached data and a full successful-fetch date when refresh fails", () => {
  render(<DashboardFreshness isCached error="取得失敗" lastSuccessAt="2026-10-28T00:00:00Z" />);
  expect(screen.getByRole("alert").textContent).toContain("保持データ");
  expect(screen.getByRole("alert").textContent).toContain("2026");
});
it("retains explicit rescue requests while warning about stale observations", () => {
  const item = applyDashboardFreshness({ shelter: { id: "A", name: "避難所" }, latest_observation: { observed_at: new Date(Date.now() - 25 * 3600000).toISOString(), water_stock: 100 }, status: "NORMAL", explicit_request_code: "REQ_RESCUE" });
  render(<ShelterCard shelterStatus={item} />);
  expect(screen.getByText("ALERT 警戒")).toBeTruthy();
  expect(screen.getByText("REQ_RESCUE")).toBeTruthy();
  expect(screen.getByText("24時間以上更新なし・要確認")).toBeTruthy();
});
