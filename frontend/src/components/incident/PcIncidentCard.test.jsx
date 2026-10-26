import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PcIncidentCard from "./PcIncidentCard.jsx";
import { approveIncidentResolutionRequest } from "../../api.js";
let user;
vi.mock("../../auth/AuthContext.jsx", () => ({ useAuth: () => ({ user }) }));
vi.mock("../../api.js", () => ({ approveIncidentResolutionRequest: vi.fn() }));
const incident = { id: "OBS-1", shelter: { id: "AIT001", name: "避難所" }, memo: "救援要請", urgency: "WARNING", resolutionRequest: { memo: "Aの申請内容", staffName: "A", requestedAt: "2026-10-26T00:00:00Z", version: 3 } };
beforeEach(() => { user = { role: "hq", shelter_ids: ["*"] }; approveIncidentResolutionRequest.mockReset(); });
afterEach(cleanup);
it("submits the displayed version and prompts review on a stale approval", async () => {
  approveIncidentResolutionRequest.mockRejectedValue(Object.assign(new Error("changed"), { status: 409 }));
  const changed = vi.fn();
  render(<PcIncidentCard incident={incident} onChanged={changed} />);
  expect(screen.getByText(/Aの申請内容/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "承認する(本部)" }));
  await screen.findByRole("alert");
  expect(approveIncidentResolutionRequest).toHaveBeenCalledWith("OBS-1", expect.objectContaining({ requestVersion: 3 }));
  expect(changed).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert").textContent).toContain("最新の内容を確認");
  await waitFor(() => expect(screen.getByRole("button", { name: "承認する(本部)" }).disabled).toBe(false));
});
it("hides approval for headquarters staff outside their assignment", () => {
  user = { role: "hq", shelter_ids: ["AIT002"] };
  render(<PcIncidentCard incident={incident} onChanged={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "承認する(本部)" })).toBeNull();
});
