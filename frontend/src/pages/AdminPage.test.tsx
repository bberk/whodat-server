import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import {
  adminUser,
  eloConfigResponse,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  leagueMembers,
  mockFetch,
  requestPath,
  seasonSettingsResponse,
} from "../test/fixtures";
import { AdminPage } from "./AdminPage";

function leagueValue(overrides: Partial<LeagueContextValue> = {}): LeagueContextValue {
  return {
    leagues: [leagueAlpha],
    leaguesStatus: "ready",
    leaguesError: null,
    selectedLeague: leagueAlpha,
    selectLeague: vi.fn(),
    seasons: [2026],
    seasonsStatus: "ready",
    seasonsError: null,
    season: 2026,
    selectSeason: vi.fn(),
    reloadSeasons: vi.fn(),
    addStoredSeason: vi.fn(),
    upsertLeague: vi.fn(),
    reloadLeagues: vi.fn(),
    dataVersion: 0,
    notifyDataChanged: vi.fn(),
    ...overrides,
  };
}

function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: "signed-in",
    user: adminUser,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  };
}

function renderPage(
  value: LeagueContextValue = leagueValue(),
  path = "/leagues/1/admin",
  auth: AuthContextValue = authValue(),
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={auth}>
        <LeagueContext.Provider value={value}>
          <Routes>
            <Route path="/leagues/:leagueId/admin" element={<AdminPage />} />
            <Route path="/" element={<p>Standings stub</p>} />
          </Routes>
        </LeagueContext.Provider>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

function defaultFetch(url: string) {
  const path = requestPath(url);
  if (path === "/api/v1/leagues/1/members") {
    return jsonResponse({ members: leagueMembers });
  }
  if (path === "/api/v1/leagues/1/seasons/settings") {
    return jsonResponse(seasonSettingsResponse);
  }
  if (path === "/api/v1/leagues/1/elo-config") {
    return jsonResponse(eloConfigResponse);
  }
  return errorResponse(404, { code: "not_found", message: path });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AdminPage", () => {
  it("mounts members, the seasons table, invites, and the danger zone", async () => {
    mockFetch(defaultFetch);

    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "League admin" })).toBeInTheDocument();
    expect(screen.getByText("Alpha League", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Members" })).toBeInTheDocument();
    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Seasons" })).toBeInTheDocument();
    expect(await screen.findByRole("rowheader", { name: "2026" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "2025" })).toBeInTheDocument();
    expect(screen.getByLabelText("Cup week for 2026")).toHaveValue("1");
    expect(screen.getByRole("button", { name: "Add a season" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Add a season" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "Cup week" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Playoff odds simulation" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2026 — current season")).toBeInTheDocument();
    expect(screen.queryByLabelText("Simulation season")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Simulations")).toHaveValue(10000);
    expect(screen.getByRole("button", { name: "Run simulations" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Elo settings" })).toBeInTheDocument();
    expect(await screen.findByLabelText("K factor")).toHaveValue("24");
    expect(screen.getByRole("heading", { level: 2, name: "Invites" })).toBeInTheDocument();
    expect(screen.getByLabelText("Invite type")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Danger zone: delete this league" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Type the league name to confirm")).toBeInTheDocument();
  });

  it("renders the seasons table when the shell has no selected season", async () => {
    mockFetch(defaultFetch);

    renderPage(leagueValue({ season: null, seasons: [] }));

    expect(screen.getByRole("heading", { level: 2, name: "Seasons" })).toBeInTheDocument();
    expect(await screen.findByRole("rowheader", { name: "2026" })).toBeInTheDocument();
    expect(screen.queryByText("No season selected")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Invites" })).toBeInTheDocument();
    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
  });

  it("selects the league named by the route when it differs from the shell selection", () => {
    const value = leagueValue({ selectedLeague: { ...leagueAlpha, league_id: 2 } });
    mockFetch(defaultFetch);

    renderPage(value);

    expect(value.selectLeague).toHaveBeenCalledWith(1);
  });

  it("returns to the standings for an invalid league id", () => {
    mockFetch(defaultFetch);

    renderPage(leagueValue(), "/leagues/not-a-number/admin");

    expect(screen.getByText("Standings stub")).toBeInTheDocument();
  });
});
