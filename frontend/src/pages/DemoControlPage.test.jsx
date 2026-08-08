import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import DemoControlPage from "./DemoControlPage.jsx";

const fetchDemoControlStatus = vi.fn();
const resetDemoData = vi.fn();

vi.mock("../api.js", () => ({
  ApiError: class ApiError extends Error {},
  fetchDemoControlStatus: (...args) => fetchDemoControlStatus(...args),
  resetDemoData: (...args) => resetDemoData(...args),
}));

vi.mock("../components/AuthStatus.jsx", () => ({
  default: () => <span>デモ管理者</span>,
}));

describe("DemoControlPage", () => {
  beforeEach(() => {
    fetchDemoControlStatus.mockResolvedValue({
      confirmation_phrase: "TSUNAGUをリセット",
      counts: { shelters: 3, observations: 8, emergency_packets: 2 },
    });
    resetDemoData.mockResolvedValue({
      reset_at: "2026-08-08T00:00:00Z",
      counts: { shelters: 3, observations: 3, emergency_packets: 1 },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    fetchDemoControlStatus.mockReset();
    resetDemoData.mockReset();
  });

  it("確認文と削除確認の両方が揃うまで初期化できない", async () => {
    render(<MemoryRouter><DemoControlPage /></MemoryRouter>);
    const button = await screen.findByRole("button", { name: "デモデータを初期化" });
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/確認のため/), {
      target: { value: "TSUNAGUをリセット" },
    });
    expect(button.disabled).toBe(true);

    fireEvent.click(screen.getByRole("checkbox"));
    expect(button.disabled).toBe(false);
  });

  it("初期化成功後に固定データの件数と完了メッセージを表示する", async () => {
    render(<MemoryRouter><DemoControlPage /></MemoryRouter>);
    await screen.findByText("現在の登録件数");
    fireEvent.change(screen.getByLabelText(/確認のため/), {
      target: { value: "TSUNAGUをリセット" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "デモデータを初期化" }));

    await waitFor(() => expect(resetDemoData).toHaveBeenCalledWith("TSUNAGUをリセット"));
    expect((await screen.findByRole("status")).textContent).toContain("デモデータを初期化しました");
  });
});
