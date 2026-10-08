import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import FieldReportForm from "./FieldReportForm.jsx";

const shelters = [{ id: "AIT001", name: "Shelter A" }];

describe("FieldReportForm", () => {
  afterEach(() => {
    cleanup();
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
