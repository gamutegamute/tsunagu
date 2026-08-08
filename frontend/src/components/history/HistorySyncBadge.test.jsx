import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import HistorySyncBadge from "./HistorySyncBadge.jsx";

describe("HistorySyncBadge(時計アイコン単体では意味が伝わらないという指摘への対応)", () => {
  afterEach(() => {
    cleanup();
  });

  it("sent: 「送信済み」ラベルとアイコンを表示する", () => {
    const { container } = render(<HistorySyncBadge status="sent" />);

    expect(container.textContent).toBe("送信済み");
    expect(container.querySelector(".history-sync-chip.sent")).not.toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("unsynced: 「未同期」ラベルとアイコンを表示する(sentとは別デザイン)", () => {
    const { container } = render(<HistorySyncBadge status="unsynced" />);

    expect(container.textContent).toBe("未同期");
    expect(container.querySelector(".history-sync-chip.unsynced")).not.toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("sentとunsyncedでSVGアイコンの中身(パス)が異なる(状態ごとに意味の異なるアイコン)", () => {
    const sent = render(<HistorySyncBadge status="sent" />);
    const sentSvg = sent.container.querySelector("svg").innerHTML;
    cleanup();

    const unsynced = render(<HistorySyncBadge status="unsynced" />);
    const unsyncedSvg = unsynced.container.querySelector("svg").innerHTML;

    expect(sentSvg).not.toBe(unsyncedSvg);
  });
});
