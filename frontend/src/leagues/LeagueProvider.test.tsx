import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { MeResponse } from "../api/types";
import {
  adminUser,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  leagueBeta,
  mockFetch,
  requestPath,
} from "../test/fixtures";
import { useLeague } from "./LeagueContext";
import { LeagueProvider } from "./LeagueProvider";

function authValue(user: MeResponse | null): AuthContextValue {
  return {
    status: user === null ? "signed-out" : "signed-in",
    user,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn(),
    logout: vi.fn(),
  };
}

function wrapperFor(user: MeResponse | null) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext.Provider value={authValue(user)}>
        <LeagueProvider>{children}</LeagueProvider>
      </AuthContext.Provider>
    );
  };
}

function leagueFetch(seasons: Record<number, number[] | "error">) {
  return mockFetch((url) => {
    const path = requestPath(url);
    if (path === "/api/v1/me/leagues") {
      return jsonResponse([leagueAlpha, leagueBeta]);
    }
    const match = path.match(/^\/api\/v1\/leagues\/(\d+)\/seasons$/);
    if (match !== null) {
      const response = seasons[Number(match[1])];
      if (response === "error") {
        return errorResponse(500, { code: "boom", message: "Seasons unavailable" });
      }
      return jsonResponse({ seasons: response ?? [] });
    }
    return errorResponse(404, { code: "not_found", message: path });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LeagueProvider", () => {
  it("selects the first league and its latest season", async () => {
    leagueFetch({ 1: [2024, 2026], 2: [2025] });
    const { result } = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(result.current.leaguesStatus).toBe("ready");
    });
    await waitFor(() => {
      expect(result.current.season).toBe(2026);
    });
    expect(result.current.selectedLeague?.league_id).toBe(1);
    expect(result.current.seasons).toEqual([2024, 2026]);

    act(() => result.current.selectSeason(2024));
    expect(result.current.season).toBe(2024);
    act(() => result.current.selectSeason(1999));
    expect(result.current.season).toBe(2024);

    act(() => result.current.selectLeague(2));
    await waitFor(() => {
      expect(result.current.season).toBe(2025);
    });
    expect(result.current.selectedLeague?.league_id).toBe(2);
  });

  it("updates memberships in place and bumps the data version", async () => {
    leagueFetch({ 1: [2026], 2: [2025], 3: [2024] });
    const { result } = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(result.current.leaguesStatus).toBe("ready");
    });

    act(() => result.current.upsertLeague({ ...leagueAlpha, name: "Renamed" }));
    expect(result.current.leagues[0].name).toBe("Renamed");

    const added = { ...leagueBeta, league_id: 3, name: "Gamma League" };
    act(() => result.current.upsertLeague(added));
    expect(result.current.leagues.map((league) => league.league_id)).toEqual([1, 2, 3]);
    expect(result.current.selectedLeague?.league_id).toBe(3);

    act(() => result.current.notifyDataChanged());
    expect(result.current.dataVersion).toBe(1);

    act(() => result.current.reloadLeagues());
    await waitFor(() => {
      expect(result.current.leaguesStatus).toBe("ready");
    });
  });

  it("merges an added season, selects it, and reloads the season list", async () => {
    const seasons: Record<number, number[]> = { 1: [2026], 2: [2025] };
    leagueFetch(seasons);
    const { result } = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(result.current.season).toBe(2026);
    });

    act(() => result.current.addStoredSeason(2025));
    expect(result.current.seasons).toEqual([2025, 2026]);
    expect(result.current.season).toBe(2025);

    seasons[1] = [2025, 2026];
    act(() => result.current.reloadSeasons());
    await waitFor(() => {
      expect(result.current.seasonsStatus).toBe("ready");
    });
    expect(result.current.seasons).toEqual([2025, 2026]);
    expect(result.current.season).toBe(2025);
  });

  it("surfaces membership and season failures", async () => {
    mockFetch(() => errorResponse(500, { code: "boom", message: "Leagues unavailable" }));
    const first = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(first.result.current.leaguesStatus).toBe("error");
    });
    expect(first.result.current.leaguesError).toBe("Leagues unavailable");
    first.unmount();

    leagueFetch({ 1: "error" });
    const second = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(second.result.current.seasonsStatus).toBe("error");
    });
    expect(second.result.current.seasonsError).toBe("Seasons unavailable");
    expect(second.result.current.season).toBeNull();
    second.unmount();

    mockFetch(() => jsonResponse([]));
    const empty = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(empty.result.current.leaguesStatus).toBe("ready");
    });
    expect(empty.result.current.selectedLeague).toBeNull();
    expect(empty.result.current.season).toBeNull();
    empty.unmount();

    leagueFetch({ 1: [] });
    const noSeasons = renderHook(() => useLeague(), { wrapper: wrapperFor(adminUser) });
    await waitFor(() => {
      expect(noSeasons.result.current.seasonsStatus).toBe("ready");
    });
    expect(noSeasons.result.current.season).toBeNull();
  });

  it("stays ready and empty when there is no signed-in user", async () => {
    const fetchMock = mockFetch(() => jsonResponse([]));
    const { result } = renderHook(() => useLeague(), { wrapper: wrapperFor(null) });
    await waitFor(() => {
      expect(result.current.leaguesStatus).toBe("ready");
    });
    expect(result.current.leagues).toEqual([]);
    expect(result.current.selectedLeague).toBeNull();
    expect(result.current.seasonsStatus).toBe("ready");
    expect(result.current.season).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
