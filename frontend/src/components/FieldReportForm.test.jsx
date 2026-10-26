import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import FieldReportForm from "./FieldReportForm.jsx";

const shelters = [{ id: "AIT001", name: "Shelter A" }];

describe("FieldReportForm", () => {
  it("retains input until durable success and blocks rapid submits", async () => {
    let finish;
    const submit = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    render(<FieldReportForm shelters={shelters} networkMode="normal" pendingReportCount={0} onSubmitReport={submit} />);
    fireEvent.change(screen.getByLabelText("報告者名"), { target: { value: "担当者" } });
    const memo = document.querySelector("textarea");
    fireEvent.change(memo, { target: { value: "救援が必要" } });
    fireEvent.submit(document.querySelector("form"));
    fireEvent.submit(document.querySelector("form"));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(memo.value).toBe("救援が必要");
    expect(screen.getByRole("button", { name: "保存・送信中..." }).disabled).toBe(true);
    await act(async () => finish("queued"));
    expect(memo.value).toBe("");
    expect(screen.getByRole("status").textContent).toContain("端末に保存");
  });

  it("retains memo and reuses the same event ID after send and storage failure", async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error("QuotaExceededError")).mockResolvedValue("sent");
    render(<FieldReportForm shelters={shelters} networkMode="normal" pendingReportCount={0} onSubmitReport={submit} />);
    const memo = document.querySelector("textarea");
    fireEvent.change(memo, { target: { value: "保持するメモ" } });
    fireEvent.submit(document.querySelector("form"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("入力を保持"));
    expect(memo.value).toBe("保持するメモ");
    fireEvent.submit(document.querySelector("form"));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("送信しました"));
    expect(submit.mock.calls[1][0].clientEventId).toBe(submit.mock.calls[0][0].clientEventId);
    expect(submit.mock.calls[1][0].observedAt).toBe(submit.mock.calls[0][0].observedAt);
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("retries unchanged input with a corrected clock after an explicit timestamp rejection", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-27T00:00:00Z"));
    const submit = vi.fn(async ({ observedAt }) => {
      if (observedAt > "2026-10-26T00:10:00.000Z") {
        throw Object.assign(new Error("check the device clock"), {
          status: 422, body: { detail: "observed_at is more than 10 minutes in the future; check the device clock" },
        });
      }
      return "sent";
    });
    render(<FieldReportForm shelters={shelters} networkMode="normal" pendingReportCount={0} onSubmitReport={submit} />);
    const memo = document.querySelector("textarea");
    fireEvent.change(memo, { target: { value: "時計を直して再送する報告" } });
    fireEvent.submit(document.querySelector("form"));
    await screen.findByRole("alert");
    expect(memo.value).toBe("時計を直して再送する報告");
    vi.setSystemTime(new Date("2026-10-26T00:00:00Z"));
    fireEvent.submit(document.querySelector("form"));
    await screen.findByRole("status");
    expect(submit.mock.calls[1][0].observedAt).toBe("2026-10-26T00:00:00.000Z");
    expect(submit.mock.calls[1][0].clientEventId).toBe(submit.mock.calls[0][0].clientEventId);
  });

  it("決定事項27: 手動切替ボタン(通常/オフライン/非常時)が存在しない", () => {
    render(
      <FieldReportForm
        shelters={shelters}
        networkMode="offline"
        offlinePhase="retrying"
        pendingReportCount={0}
        onSubmitReport={vi.fn()}
      />,
    );

    for (const label of ["通常", "オフライン", "非常時"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
    // 通信状態を切り替えるボタン群のコンテナ自体が存在しないこと
    expect(document.querySelector(".mode-controls")).toBeNull();
  });

  it("オフライン・retryingフェーズでは「オフラインを検知しています」を表示する", () => {
    render(
      <FieldReportForm
        shelters={shelters}
        networkMode="offline"
        offlinePhase="retrying"
        pendingReportCount={0}
        onSubmitReport={vi.fn()}
      />,
    );

    expect(screen.getByText("オフラインを検知しています")).not.toBeNull();
  });

  it("決定事項29: オフライン・lora-availableフェーズではT-Beamの非常用Wi-Fiへの案内を表示する(送信ボタンは出さない)", () => {
    render(
      <FieldReportForm
        shelters={shelters}
        networkMode="offline"
        offlinePhase="lora-available"
        pendingReportCount={0}
        onSubmitReport={vi.fn()}
      />,
    );

    expect(screen.getByText(/名前が「TSUNAGU-」で始まるもの/)).not.toBeNull();
    // 古いWi-Fi名(特定の端末名)を画面に出さない
    expect(screen.queryByText(/TSUNAGU-Emergency/)).toBeNull();
    expect(screen.getByText(/別画面から報告してください/)).not.toBeNull();
    // LoRaを実際に送信するボタンはこのアプリ側には存在しない
    expect(screen.queryByRole("button", { name: /LoRa/ })).toBeNull();
  });

  it("通常時はバナーを表示しない", () => {
    render(
      <FieldReportForm
        shelters={shelters}
        networkMode="normal"
        offlinePhase="retrying"
        pendingReportCount={0}
        onSubmitReport={vi.fn()}
      />,
    );

    expect(screen.queryByText(/オフライン/)).toBeNull();
    expect(screen.queryByText(/LoRa/)).toBeNull();
  });

  it("決定事項33-d: 人数・水・避難所選択・報告者名の入力欄が文字拡大クラスを持つ(高齢者アクセシビリティ配慮)", () => {
    render(
      <FieldReportForm
        shelters={shelters}
        networkMode="normal"
        offlinePhase="retrying"
        pendingReportCount={0}
        onSubmitReport={vi.fn()}
      />,
    );

    const largeFields = document.querySelectorAll(".field-input-large");
    expect(largeFields.length).toBe(4);
    for (const field of largeFields) {
      expect(["INPUT", "SELECT"]).toContain(field.tagName);
    }
  });
});
