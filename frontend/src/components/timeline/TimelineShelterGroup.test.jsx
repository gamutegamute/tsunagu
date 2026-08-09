import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TimelineShelterGroup from "./TimelineShelterGroup.jsx";
import { fetchShelterObservations } from "../../api.js";

vi.mock("../../api.js", () => ({
  fetchShelterObservations: vi.fn(),
}));

const shelter = { id: "AIT001", name: "体育館" };

const latestObservation = {
  id: "OBS-latest",
  people_count: 100,
  water_stock: 20,
  urgency: "NORMAL",
  memo: "最新の報告",
  reporter_name: "田中",
  observed_at: "2026-08-09T03:00:00.000Z",
  source: "web",
};

describe("TimelineShelterGroup(過去の報告履歴を遡って見る機能)", () => {
  beforeEach(() => {
    fetchShelterObservations.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("初期表示では最新の報告のみを表示し、過去の報告取得APIは呼ばれない", () => {
    render(<TimelineShelterGroup shelter={shelter} latestObservation={latestObservation} />);

    expect(screen.getByText("最新の報告")).not.toBeNull();
    expect(fetchShelterObservations).not.toHaveBeenCalled();
  });

  it("「過去の報告を見る」を押すと履歴APIを呼び、最新以外の過去の報告を追加表示する", async () => {
    fetchShelterObservations.mockResolvedValue([
      latestObservation,
      { ...latestObservation, id: "OBS-past-1", memo: "1件前の報告", observed_at: "2026-08-09T02:00:00.000Z" },
      { ...latestObservation, id: "OBS-past-2", memo: "2件前の報告", observed_at: "2026-08-09T01:00:00.000Z" },
    ]);

    render(<TimelineShelterGroup shelter={shelter} latestObservation={latestObservation} />);
    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));

    expect(fetchShelterObservations).toHaveBeenCalledWith("AIT001");
    await waitFor(() => expect(screen.getByText("1件前の報告")).not.toBeNull());
    expect(screen.getByText("2件前の報告")).not.toBeNull();

    // 最新の報告(latestObservation)は、常に表示されている1件だけで重複表示されない
    expect(screen.getAllByText("最新の報告")).toHaveLength(1);
  });

  it("もう一度押すと閉じて、再展開してもAPIは再度呼ばれない(キャッシュを使い回す)", async () => {
    fetchShelterObservations.mockResolvedValue([latestObservation]);
    render(<TimelineShelterGroup shelter={shelter} latestObservation={latestObservation} />);

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));
    await waitFor(() => expect(screen.getByText("過去の報告はありません")).not.toBeNull());
    expect(fetchShelterObservations).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を閉じる/ }));
    expect(screen.queryByText("過去の報告はありません")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));
    expect(screen.getByText("過去の報告はありません")).not.toBeNull();
    expect(fetchShelterObservations).toHaveBeenCalledTimes(1);
  });

  it("過去の報告が最新の1件のみの場合、「過去の報告はありません」と表示する", async () => {
    fetchShelterObservations.mockResolvedValue([latestObservation]);
    render(<TimelineShelterGroup shelter={shelter} latestObservation={latestObservation} />);

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));

    await waitFor(() => expect(screen.getByText("過去の報告はありません")).not.toBeNull());
  });

  it("履歴取得に失敗した場合はエラーメッセージを表示する", async () => {
    fetchShelterObservations.mockRejectedValue(new Error("network error"));
    render(<TimelineShelterGroup shelter={shelter} latestObservation={latestObservation} />);

    fireEvent.click(screen.getByRole("button", { name: /過去の報告を見る/ }));

    await waitFor(() => expect(screen.getByText("過去の報告履歴の取得に失敗しました")).not.toBeNull());
  });
});
