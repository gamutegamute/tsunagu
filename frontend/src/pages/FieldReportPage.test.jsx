import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import FieldReportPage from "./FieldReportPage.jsx";
import { STORAGE_KEYS } from "../utils/storageKeys.js";

vi.mock("../auth/AuthContext.jsx", () => ({
  useAuth: () => ({ user: null, signOut: vi.fn() }),
}));

vi.mock("../hooks/useShelterList.js", () => ({
  useShelterList: () => [{ id: "AIT001", name: "Shelter A" }],
}));

let mockNetworkMode = "normal";
let mockOfflinePhase = "retrying";
vi.mock("../hooks/useNetworkMode.js", () => ({
  useNetworkMode: () => [mockNetworkMode, mockOfflinePhase],
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <FieldReportPage />
    </MemoryRouter>,
  );
}

async function submitReport() {
  fireEvent.change(screen.getByLabelText("報告者名"), { target: { value: "テスト太郎" } });
  fireEvent.click(screen.getByRole("button", { name: "報告する" }));
}

function readPendingReports() {
  return JSON.parse(localStorage.getItem(STORAGE_KEYS.pendingReports) || "[]");
}

describe("FieldReportPage — 決定事項29: オフライン中の報告は未送信キューに保存するのみ", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("オフライン(retryingフェーズ)で報告すると、未送信キューに保存される", async () => {
    mockNetworkMode = "offline";
    mockOfflinePhase = "retrying";
    renderPage();

    await submitReport();

    const pending = readPendingReports();
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ shelter_id: "AIT001", reporter_name: "テスト太郎", source: "offline" });
  });

  it("「LoRa使用可」(lora-availableフェーズ)で報告しても、送信処理は呼ばれず未送信キューに保存されるだけ", async () => {
    mockNetworkMode = "offline";
    mockOfflinePhase = "lora-available";
    renderPage();

    await submitReport();

    const pending = readPendingReports();
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ shelter_id: "AIT001", reporter_name: "テスト太郎", source: "offline" });
  });

  it("画面上にLoRaを直接送信するボタン・操作は存在しない(T-Beam専用ページの案内表示のみ)", () => {
    mockNetworkMode = "offline";
    mockOfflinePhase = "lora-available";
    renderPage();

    expect(screen.getByText(/TSUNAGU-Emergency/)).not.toBeNull();
    expect(screen.queryByRole("button", { name: /LoRa/ })).toBeNull();
  });
});
