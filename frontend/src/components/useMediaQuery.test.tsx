import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useMediaQuery } from "./useMediaQuery";

type Listener = (event: MediaQueryListEvent) => void;

interface MatchMediaStub {
  listeners: Listener[];
}

function installMatchMedia(initial: boolean): MatchMediaStub {
  const listeners: Listener[] = [];
  const list = {
    matches: initial,
    media: "(max-width: 767px)",
    onchange: null,
    addEventListener: (_type: string, listener: Listener) => {
      listeners.push(listener);
    },
    removeEventListener: (_type: string, listener: Listener) => {
      const index = listeners.indexOf(listener);
      if (index >= 0) {
        listeners.splice(index, 1);
      }
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => true,
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: () => list,
  });
  return { listeners };
}

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
});

describe("useMediaQuery", () => {
  it("returns false when matchMedia is unavailable", () => {
    const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
    expect(result.current).toBe(false);
  });

  it("reports the initial match and reacts to changes", () => {
    const stub = installMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
    expect(result.current).toBe(false);
    act(() => {
      stub.listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent));
    });
    expect(result.current).toBe(true);
  });

  it("starts true when the query already matches", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
    expect(result.current).toBe(true);
  });

  it("removes its change listener on unmount", () => {
    const stub = installMatchMedia(false);
    const { unmount } = renderHook(() => useMediaQuery("(max-width: 767px)"));
    expect(stub.listeners).toHaveLength(1);
    unmount();
    expect(stub.listeners).toHaveLength(0);
  });
});
