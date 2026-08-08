import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import AddShelterModal from "./AddShelterModal.jsx";
import { createShelter } from "../api.js";

vi.mock("../api.js", () => ({
  createShelter: vi.fn(),
}));

describe("AddShelterModal", () => {
  beforeEach(() => {
    createShelter.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("避難所ID入力欄の値を requested_id ではなく id としてバックエンドへ送信する", async () => {
    createShelter.mockResolvedValue({ id: "AIT001", name: "愛知工業大学 体育館", location: "" });
    const onCreated = vi.fn();

    render(<AddShelterModal onCancel={vi.fn()} onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText("避難所名"), { target: { value: "愛知工業大学 体育館" } });
    fireEvent.change(screen.getByLabelText("避難所ID"), { target: { value: "AIT001" } });
    fireEvent.click(screen.getByRole("button", { name: "登録する" }));

    await waitFor(() => expect(createShelter).toHaveBeenCalledTimes(1));
    expect(createShelter).toHaveBeenCalledWith({ name: "愛知工業大学 体育館", id: "AIT001", capacity: undefined });
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  });

  it("避難所IDが未入力の場合は id を undefined として送信する(サーバー側自動採番)", async () => {
    createShelter.mockResolvedValue({ id: "SH-AUTO", name: "テスト避難所", location: "" });

    render(<AddShelterModal onCancel={vi.fn()} onCreated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("避難所名"), { target: { value: "テスト避難所" } });
    fireEvent.click(screen.getByRole("button", { name: "登録する" }));

    await waitFor(() => expect(createShelter).toHaveBeenCalledTimes(1));
    expect(createShelter).toHaveBeenCalledWith({ name: "テスト避難所", id: undefined, capacity: undefined });
  });

  it("決定事項34-b: キャパシティを入力すると、POST /api/sheltersのペイロードに数値として含める", async () => {
    createShelter.mockResolvedValue({ id: "AIT001", name: "愛知工業大学 体育館", location: "", capacity: 170 });

    render(<AddShelterModal onCancel={vi.fn()} onCreated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("避難所名"), { target: { value: "愛知工業大学 体育館" } });
    fireEvent.change(screen.getByPlaceholderText("例: 170"), { target: { value: "170" } });
    fireEvent.click(screen.getByRole("button", { name: "登録する" }));

    await waitFor(() => expect(createShelter).toHaveBeenCalledTimes(1));
    expect(createShelter).toHaveBeenCalledWith({ name: "愛知工業大学 体育館", id: undefined, capacity: 170 });
  });
});
