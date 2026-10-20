import { render, screen, waitFor } from "@testing-library/react";
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

function renderPage(value: LeagueContextValue = leagueValue(), path = "/leagues/1/owner") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LeagueContext.Provider value={value}>
        <Routes>
          <Route path="/leagues/:leagueId/owner" element={<OwnerPage />} />
          <Route path="/" element={<p>Standings stub</p>} />
        </Routes>
      </LeagueContext.Provider>
    </MemoryRouter>,
  );
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
    await user.selectOptions(select, "");
    expect(select).toHaveValue("");
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
    const user = userEvent.setup();
    const fetchMock = mockFetch(() =>
      errorResponse(404, { code: "not_found", message: "League not found" }),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("League not found");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });

  it("shows a structured error when saving fails", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/owners") {
        return jsonResponse({ owners });
      }
      if (init.method === "PUT") {
        return errorResponse(422, [
          { loc: ["body", "owner_id"], msg: "Owner is not available", type: "value_error" },
        ]);
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });
    renderPage();
    await screen.findByLabelText("Owner");
    await user.click(screen.getByRole("button", { name: "Save owner" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Owner is not available");
    });
  });

  it("rejects an invalid league id and falls back to the selected league", async () => {
    const first = renderPage(leagueValue(), "/leagues/not-a-number/owner");
    expect(await screen.findByRole("alert")).toHaveTextContent("This league id is not valid.");
    first.unmount();

    mockFetch(() => jsonResponse({ owners }));
    renderPage(leagueValue({ leagues: [], selectedLeague: leagueAlpha }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Owner · Alpha League" }),
    ).toBeInTheDocument();
  });
});
