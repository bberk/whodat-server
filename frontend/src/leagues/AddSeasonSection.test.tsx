import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";
import { AddSeasonSection } from "./AddSeasonSection";
import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";

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

function renderSection(value: LeagueContextValue = leagueValue()) {
  return render(
    <LeagueContext.Provider value={value}>
      <AddSeasonSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AddSeasonSection", () => {
  it("adds a season, refreshes the season list, and selects the new season", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    const fetchMock = mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/seasons" && init.method === "POST") {
        expect(requestBody(init)).toEqual({ season: 2025 });
        return jsonResponse({ league_id: 1, season: 2025, weeks_synced: [1, 2] }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });
    renderSection(value);

    const input = screen.getByLabelText("Season year");
    await user.clear(input);
    await user.type(input, "2025");
    await user.click(screen.getByRole("button", { name: "Add season" }));

    expect(await screen.findByText("Season 2025 added and synced.")).toBeInTheDocument();
    expect(value.addStoredSeason).toHaveBeenCalledWith(2025);
    expect(value.reloadSeasons).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a loading state while the sync is running", async () => {
    const user = userEvent.setup();
    let resolveResponse: ((response: Response) => void) | undefined;
    mockFetch(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: "Add season" }));

    expect(screen.getByRole("button", { name: "Adding…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Adding and syncing season…");
    expect(screen.getByLabelText("Season year")).toBeDisabled();

    resolveResponse?.(
      jsonResponse({ league_id: 1, season: 2025, weeks_synced: [] }, { status: 201 }),
    );
    expect(await screen.findByText("Season 2025 added and synced.")).toBeInTheDocument();
  });

  it("rejects an empty or out-of-range year before calling the API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => jsonResponse({}));
    renderSection();
    const input = screen.getByLabelText("Season year");

    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Add season" }));
    expect(
      screen.getByText("Enter a whole season year between 2000 and 2100."),
    ).toBeInTheDocument();

    await user.type(input, "1999");
    await user.click(screen.getByRole("button", { name: "Add season" }));
    expect(
      screen.getByText("Season must be a whole year between 2000 and 2100."),
    ).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "2025.5");
    await user.click(screen.getByRole("button", { name: "Add season" }));
    expect(
      screen.getByText("Enter a whole season year between 2000 and 2100."),
    ).toBeInTheDocument();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the server's structured error when the season already exists", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    mockFetch(() =>
      errorResponse(409, {
        code: "season_exists",
        message: "This season already exists for this league",
      }),
    );
    renderSection(value);

    await user.click(screen.getByRole("button", { name: "Add season" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "This season already exists for this league",
      );
    });
    expect(value.addStoredSeason).not.toHaveBeenCalled();
    expect(value.reloadSeasons).not.toHaveBeenCalled();
  });
});
