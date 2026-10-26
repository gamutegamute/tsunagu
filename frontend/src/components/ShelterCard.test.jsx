import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ShelterCard from "./ShelterCard.jsx";
afterEach(cleanup);
function item(signature = "SIGNATURE_VALID") {
  return { shelter: { id: "AIT001", name: "避難所" }, status: "CRITICAL", request_code: "REQ_RESCUE", explicit_request_code: "REQ_RESCUE", derived_request_code: "REQ_WATER", latest_observation: { source: "emergency_packet", signature_status: signature, verification_status: "UNVERIFIED" } };
}
it.each(["REQ_RESCUE", "REQ_MEDICAL", "REQ_FOOD"])("shows explicit %s alongside the derived water request", (request) => {
  render(<ShelterCard shelterStatus={{ ...item(), request_code: request }} />);
  expect(screen.getByText(request)).toBeTruthy();
  expect(screen.getByText("補助判定: REQ_WATER")).toBeTruthy();
  expect(screen.getByText("送信元: 署名検証済み(v2)")).toBeTruthy();
  expect(screen.getByText("未確認")).toBeTruthy();
});
it("distinguishes unsigned v1 from web reports", () => {
  const { rerender } = render(<ShelterCard shelterStatus={item("UNSIGNED_V1")} />);
  expect(screen.getByText("送信元: 署名なし(v1)")).toBeTruthy();
  rerender(<ShelterCard shelterStatus={{ ...item(), latest_observation: { source: "web" } }} />);
  expect(screen.getByText("送信元: Web報告")).toBeTruthy();
});
