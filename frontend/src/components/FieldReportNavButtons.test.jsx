import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import FieldReportNavButtons from "./FieldReportNavButtons.jsx";

vi.mock("../auth/AuthContext.jsx", () => ({
  useAuth: () => ({ user: null }),
}));

describe("FieldReportNavButtons(時計アイコンだけでは何のボタンか分からないという指摘への対応)", () => {
  afterEach(() => {
    cleanup();
  });

  it("送信履歴への導線は、アイコンではなく「送信履歴」という文字ラベルのボタンで表示する", () => {
    render(
      <MemoryRouter>
        <FieldReportNavButtons />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "送信履歴" });
    expect(link.textContent.trim()).toBe("送信履歴");
    expect(link.getAttribute("href")).toBe("/history");
  });
});
