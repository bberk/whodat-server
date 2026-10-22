import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import { errorResponse, jsonResponse, leagueAlpha, mockFetch, requestPath } from "../test/fixtures";
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

function renderPage(value: LeagueContextValue = leagueValue(), path = "/leagues/1/admin") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LeagueContext.Provider value={value}>
        <Routes>
          <Route path="/leagues/:leagueId/admin" element={<AdminPage />} />
          <Route path="/" element={<p>Standings stub</p>} />
        </Routes>
      </LeagueContext.Provider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AdminPage", () => {
  it("mounts the add-season and cup-week sections on one admin page", async () => {
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/2026/cup-week") {
        return jsonResponse({ season: 2026, cup_week: 1, regular_season_length: 2 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });

    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "League admin" })).toBeInTheDocument();
    expect(screen.getByText("Alpha League")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Add a season" })).toBeInTheDocument();
    expect(screen.getByLabelText("Season year")).toBeInTheDocument();
    expect(await screen.findByLabelText("Cup week for this season")).toHaveValue("1");
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(2);
  });

  it("keeps the add-season section when no season is selected", () => {
    renderPage(leagueValue({ season: null, seasons: [] }));

    expect(screen.getByRole("heading", { level: 2, name: "Add a season" })).toBeInTheDocument();
    expect(screen.getByText("No season selected")).toBeInTheDocument();
    expect(screen.queryByLabelText("Cup week for this season")).not.toBeInTheDocument();
  });

  it("selects the league named by the route when it differs from the shell selection", () => {
    const value = leagueValue({ selectedLeague: { ...leagueAlpha, league_id: 2 } });
    mockFetch(() => jsonResponse({ season: 2026, cup_week: null, regular_season_length: 2 }));

    renderPage(value);

    expect(value.selectLeague).toHaveBeenCalledWith(1);
  });

  it("returns to the standings for an invalid league id", () => {
    renderPage(leagueValue(), "/leagues/not-a-number/admin");

    expect(screen.getByText("Standings stub")).toBeInTheDocument();
  });
});
