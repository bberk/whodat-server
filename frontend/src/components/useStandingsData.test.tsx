import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  createStandingsSource,
  mockStandingsBundle,
  type StandingsSource,
} from "../mocks/standings";
import { useStandingsData } from "./useStandingsData";

describe("useStandingsData", () => {
  it("starts in the loading state", () => {
    const source = createStandingsSource("loading");
    const { result } = renderHook(() => useStandingsData(source));
    expect(result.current.state).toEqual({ status: "loading" });
  });

  it("resolves to ready with the loaded bundle", async () => {
    const source = createStandingsSource("ready");
    const { result } = renderHook(() => useStandingsData(source));
    await waitFor(() => {
      expect(result.current.state.status).toBe("ready");
    });
    expect(result.current.state).toEqual({ status: "ready", bundle: mockStandingsBundle });
  });

  it("resolves to empty when the season has no rows", async () => {
    const source = createStandingsSource("empty");
    const { result } = renderHook(() => useStandingsData(source));
    await waitFor(() => {
      expect(result.current.state.status).toBe("empty");
    });
  });

  it("resolves to error with the thrown message", async () => {
    const source = createStandingsSource("error");
    const { result } = renderHook(() => useStandingsData(source));
    await waitFor(() => {
      expect(result.current.state.status).toBe("error");
    });
    expect(result.current.state).toEqual({
      status: "error",
      message: "The standings request failed",
    });
  });

  it("falls back to a generic message when the rejection is not an Error", async () => {
    const source: StandingsSource = { load: () => Promise.reject("nope") };
    const { result } = renderHook(() => useStandingsData(source));
    await waitFor(() => {
      expect(result.current.state.status).toBe("error");
    });
    expect(result.current.state).toEqual({ status: "error", message: "The request failed" });
  });

  it("retries after a failure and then reports ready", async () => {
    let calls = 0;
    const source: StandingsSource = {
      load: () => {
        calls += 1;
        return calls === 1
          ? Promise.reject(new Error("boom"))
          : Promise.resolve(mockStandingsBundle);
      },
    };
    const { result } = renderHook(() => useStandingsData(source));
    await waitFor(() => {
      expect(result.current.state.status).toBe("error");
    });
    act(() => {
      result.current.reload();
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("ready");
    });
  });
});
