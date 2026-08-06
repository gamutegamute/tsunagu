import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboardPolling } from "./useDashboardPolling.js";

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

describe("useDashboardPolling(決定事項33-b)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("マウント時に即座に1回コールバックを呼ぶ", () => {
    const callback = vi.fn();
    renderHook(() => useDashboardPolling(callback, 15_000));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("指定間隔(15秒)ごとに自動的にコールバックを呼び続ける", () => {
    const callback = vi.fn();
    renderHook(() => useDashboardPolling(callback, 15_000));
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(15_000));
    expect(callback).toHaveBeenCalledTimes(2);

    act(() => vi.advanceTimersByTime(15_000));
    expect(callback).toHaveBeenCalledTimes(3);

    act(() => vi.advanceTimersByTime(44_000));
    expect(callback).toHaveBeenCalledTimes(5);
  });

  it("タブが非表示になっている間は自動更新を止める", () => {
    const callback = vi.fn();
    renderHook(() => useDashboardPolling(callback, 15_000));
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      setVisibility("hidden");
      document.dispatchEvent(new Event("visibilitychange"));
    });

    act(() => vi.advanceTimersByTime(60_000));
    // 非表示化のタイミングで呼ばれないため、マウント時の1回のみのまま
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("再びタブが表示されたら、即座に最新化してからポーリングを再開する", () => {
    const callback = vi.fn();
    renderHook(() => useDashboardPolling(callback, 15_000));
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      setVisibility("hidden");
      document.dispatchEvent(new Event("visibilitychange"));
    });
    act(() => vi.advanceTimersByTime(60_000));
    expect(callback).toHaveBeenCalledTimes(1);

    act(() => {
      setVisibility("visible");
      document.dispatchEvent(new Event("visibilitychange"));
    });
    // 再表示された瞬間に1回即時実行される
    expect(callback).toHaveBeenCalledTimes(2);

    act(() => vi.advanceTimersByTime(15_000));
    expect(callback).toHaveBeenCalledTimes(3);
  });

  it("アンマウント時にポーリングを停止する", () => {
    const callback = vi.fn();
    const { unmount } = renderHook(() => useDashboardPolling(callback, 15_000));
    expect(callback).toHaveBeenCalledTimes(1);

    unmount();

    act(() => vi.advanceTimersByTime(60_000));
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("callbackの参照が毎レンダー変わっても、intervalは張り直さず最新のcallbackを呼ぶ", () => {
    const callback1 = vi.fn();
    const callback2 = vi.fn();
    const { rerender } = renderHook(({ cb }) => useDashboardPolling(cb, 15_000), {
      initialProps: { cb: callback1 },
    });
    expect(callback1).toHaveBeenCalledTimes(1);

    rerender({ cb: callback2 });

    act(() => vi.advanceTimersByTime(15_000));
    expect(callback1).toHaveBeenCalledTimes(1);
    expect(callback2).toHaveBeenCalledTimes(1);
  });
});
