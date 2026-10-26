import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import RequireApprover from "./RequireApprover.jsx";
import IncidentPage from "./IncidentPage.jsx";
import { fetchIncidents } from "../api.js";

let user;
vi.mock("../auth/AuthContext.jsx", () => ({ useAuth: () => ({ user, loading: false }) }));
vi.mock("../hooks/useShelterList.js", () => ({ useShelterList: () => [] }));
vi.mock("../api.js", () => ({ fetchIncidents: vi.fn() }));

function incident(id, shelter) {
  return { id, shelter: { id: shelter, name: shelter }, urgency: "WARNING", memo: `問題${id}`, observed_at: "2026-10-26T00:00:00Z", state: { confirm_status: "UNCONFIRMED" } };
}
function openPage() {
  return render(<MemoryRouter initialEntries={["/incident"]}><Routes>
    <Route path="/incident" element={<RequireApprover allowField><IncidentPage /></RequireApprover>} />
    <Route path="/login" element={<p>ログイン画面</p>} />
    <Route path="/field-report" element={<p>現場報告画面</p>} />
  </Routes></MemoryRouter>);
}
describe("incident access and assigned shelter actions", () => {
  beforeEach(() => { fetchIncidents.mockReset().mockResolvedValue([incident("1", "AIT001"), incident("2", "AIT002")]); });
  afterEach(cleanup);
  it("redirects anonymous users to login without fetching incidents", () => {
    user = null;
    openPage();
    expect(screen.getByText("ログイン画面")).toBeTruthy();
    expect(fetchIncidents).not.toHaveBeenCalled();
  });
  it("lets field staff read all shelters but only request their assignment", async () => {
    user = { role: "field", shelter_ids: ["AIT001"] };
    openPage();
    await screen.findByText("問題1");
    expect(screen.getByText("問題2")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "対応済みにする" })).toHaveLength(1);
    expect(screen.queryByText("承認する(本部)")).toBeNull();
  });
  it("lets headquarters staff enter the mobile incident page", async () => {
    user = { role: "hq", shelter_ids: ["*"] };
    openPage();
    await screen.findByText("問題1");
    expect(screen.getAllByRole("button", { name: "対応済みにする" })).toHaveLength(2);
  });
  it("shows a fetch failure and retry instead of an empty list", async () => {
    user = { role: "field", shelter_ids: [] };
    fetchIncidents.mockRejectedValueOnce(new Error("403"));
    openPage();
    await screen.findByRole("alert");
    expect(screen.queryByText("該当するインシデントはありません")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "再取得" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByText("問題1")).toBeTruthy();
  });
});
