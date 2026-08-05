import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNetworkMode } from "./useNetworkMode.js";

describe("useNetworkMode", () => {
  let online;

  beforeEach(() => {
    online = true;
    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      get: () => online,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("回線断を検知し、API復旧時に未送信データの同期を呼ぶ", async () => {
    const onBackOnline = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useNetworkMode(onBackOnline));

    await waitFor(() => expect(result.current[0]).toBe("normal"));
    expect(onBackOnline).toHaveBeenCalledTimes(1);

    online = false;
    act(() => window.dispatchEvent(new Event("offline")));
    expect(result.current[0]).toBe("offline");

    online = true;
    act(() => window.dispatchEvent(new Event("online")));
    await waitFor(() => expect(result.current[0]).toBe("normal"));
    expect(onBackOnline).toHaveBeenCalledTimes(2);
  });

  it("ブラウザがオンラインでもAPIへ到達できなければオフライン扱いにする", async () => {
    fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useNetworkMode(vi.fn()));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(result.current[0]).toBe("offline");
  });

  it("手動切替ボタンで「通常」に戻したときも未送信データの同期を呼ぶ(変化がない場合は呼ばない)", async () => {
    const onBackOnline = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useNetworkMode(onBackOnline));

    await waitFor(() => expect(result.current[0]).toBe("normal"));
    expect(onBackOnline).toHaveBeenCalledTimes(1); // 初回マウント時の自動検知

    const [, setNetworkMode] = result.current;

    act(() => setNetworkMode("offline"));
    expect(result.current[0]).toBe("offline");
    expect(onBackOnline).toHaveBeenCalledTimes(1); // 「通常」→「オフライン」では呼ばれない

    act(() => setNetworkMode("normal"));
    expect(result.current[0]).toBe("normal");
    expect(onBackOnline).toHaveBeenCalledTimes(2); // 「オフライン」→「通常」の手動切替で呼ばれる

    act(() => setNetworkMode("normal"));
    expect(onBackOnline).toHaveBeenCalledTimes(2); // 「通常」→「通常」(変化なし)では呼ばれない

    act(() => setNetworkMode("emergency"));
    expect(result.current[0]).toBe("emergency");
    expect(onBackOnline).toHaveBeenCalledTimes(2); // 「通常」→「非常時」では呼ばれない

    act(() => setNetworkMode("normal"));
    expect(result.current[0]).toBe("normal");
    expect(onBackOnline).toHaveBeenCalledTimes(3); // 「非常時」→「通常」の手動切替で呼ばれる
  });
});
