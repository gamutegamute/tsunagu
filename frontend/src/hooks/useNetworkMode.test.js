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
    vi.useRealTimers();
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

  it("表示モードは normal/offline の2値のみで、非常時に相当する値は返さない", async () => {
    fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useNetworkMode(vi.fn()));

    await waitFor(() => expect(result.current[0]).toBe("offline"));
    expect(["normal", "offline"]).toContain(result.current[0]);
  });

  describe("オフライン内の「LoRa使用可」フェーズ(決定事項27)", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    it("オフライン判定から10秒未満で復旧した場合、「LoRa使用可」にならない", async () => {
      fetch.mockRejectedValue(new TypeError("Failed to fetch"));
      const onBackOnline = vi.fn().mockResolvedValue(undefined);
      const { result } = renderHook(() => useNetworkMode(onBackOnline));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current[0]).toBe("offline");
      expect(result.current[1]).toBe("retrying");

      // 10秒未満(9秒)経過した時点ではまだ「LoRa使用可」にならない
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9_000);
      });
      expect(result.current[1]).toBe("retrying");

      // この時点で通信が復旧すれば、そのままnormalへ戻る
      fetch.mockResolvedValue({ ok: true });
      online = true;
      await act(async () => {
        window.dispatchEvent(new Event("online"));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current[0]).toBe("normal");
      expect(onBackOnline).toHaveBeenCalledTimes(1);

      // 復旧後は10秒以上経っても「LoRa使用可」にはならない(タイマーが解除されている)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(result.current[0]).toBe("normal");
      expect(result.current[1]).toBe("retrying");
    });

    it("オフライン判定から10秒経過すると、自動的に「LoRa使用可」になる(ただし自動送信はしない)", async () => {
      fetch.mockRejectedValue(new TypeError("Failed to fetch"));
      const { result } = renderHook(() => useNetworkMode(vi.fn()));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current[0]).toBe("offline");
      expect(result.current[1]).toBe("retrying");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });

      expect(result.current[0]).toBe("offline");
      expect(result.current[1]).toBe("lora-available");
    });

    it("「LoRa使用可」の状態でも通信が復旧すればnormalへ自動的に戻る", async () => {
      fetch.mockRejectedValue(new TypeError("Failed to fetch"));
      const onBackOnline = vi.fn().mockResolvedValue(undefined);
      const { result } = renderHook(() => useNetworkMode(onBackOnline));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current[0]).toBe("offline");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(result.current[1]).toBe("lora-available");

      fetch.mockResolvedValue({ ok: true });
      online = true;
      await act(async () => {
        window.dispatchEvent(new Event("online"));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(result.current[0]).toBe("normal");
      expect(onBackOnline).toHaveBeenCalledTimes(1);
    });
  });
});
