import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import {
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  owners,
  requestBody,
  requestPath,
} from "../test/fixtures";
import { OwnerPage } from "./OwnerPage";

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
    upsertLeague: vi.fn(),
    reloadLeagues: vi.fn(),
    dataVersion: 0,
    notifyDataChanged: vi.fn(),
    ...overrides,
  };
}

function renderPage(value: LeagueContextValue = leagueValue()) {
  render(
    <MemoryRouter initialEntries={["/leagues/1/owner"]}>
      <LeagueContext.Provider value={value}>
        <Routes>
          <Route path="/leagues/:leagueId/owner" element={<OwnerPage />} />
          <Route path="/" element={<p>Standings stub</p>} />
        </Routes>
      </LeagueContext.Provider>
    </MemoryRouter>,
  );
  return value;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OwnerPage", () => {
  it("loads the league owners and saves the caller's own owner", async () => {
    const user = userEvent.setup();
    const league = leagueValue();
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/owners") {
        return jsonResponse({ owners });
      }
      if (path === "/api/v1/me/leagues/1/owner" && init.method === "PUT") {
        expect(requestBody(init)).toEqual({ owner_id: 3 });
        return jsonResponse({ league: { ...leagueAlpha, owner_id: 3 } });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });

    renderPage(league);
    const select = await screen.findByLabelText("Owner");
    expect(select).toHaveValue("7");
    await user.selectOptions(select, "3");
    await user.click(screen.getByRole("button", { name: "Save owner" }));

    expect(await screen.findByText("Owner saved.")).toBeInTheDocument();
    expect(league.upsertLeague).toHaveBeenCalledWith({ ...leagueAlpha, owner_id: 3 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows an empty state when the league has no owners", async () => {
    mockFetch(() => jsonResponse({ owners: [] }));
    renderPage();
    expect(await screen.findByText("No owners yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Owner")).not.toBeInTheDocument();
  });

  it("shows an error state with retry when owners cannot be loaded", async () => {
    mockFetch(() => errorResponse(404, { code: "not_found", message: "League not found" }));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("League not found");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
