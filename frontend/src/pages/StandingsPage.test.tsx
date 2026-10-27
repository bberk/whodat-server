import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import {
  emptyHistoryResponse,
  emptyPlayoffOddsResponse,
  emptyStandingsResponse,
  emptyWapdateResponse,
  errorResponse,
  historyResponse,
  jsonResponse,
  leagueAlpha,
  memberUser,
  mockFetch,
  playoffOddsResponse,
  requestPath,
  standingsResponse,
  wapdateResponse,
} from "../test/fixtures";
import { StandingsPage } from "./StandingsPage";

function contextValue(overrides: Partial<LeagueContextValue> = {}): LeagueContextValue {
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

function authValue(): AuthContextValue {
  return {
    status: "signed-in",
    user: memberUser,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn(),
    logout: vi.fn(),
  };
}

function renderPage(value: LeagueContextValue = contextValue()) {
  return render(
    <AuthContext.Provider value={authValue()}>
      <LeagueContext.Provider value={value}>
        <StandingsPage />
      </LeagueContext.Provider>
    </AuthContext.Provider>,
  );
}

function readyFetch() {
  return mockFetch((url) => {
    const path = requestPath(url);
    if (path.endsWith("/standings")) {
      return jsonResponse(standingsResponse);
    }
    if (path.endsWith("/vp-history")) {
      return jsonResponse(historyResponse);
    }
    if (path.endsWith("/wapdate")) {
      return jsonResponse(wapdateResponse);
    }
    if (path.endsWith("/playoff-odds")) {
      return jsonResponse(playoffOddsResponse);
    }
    return errorResponse(404, { code: "not_found", message: "Not found" });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StandingsPage", () => {
  it("renders the overall table, one table per division, and the chart", async () => {
    readyFetch();
    renderPage();
    const overall = await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(within(overall).getByRole("columnheader", { name: "W-L" })).toBeInTheDocument();
    const east = screen.getByRole("table", { name: /east division standings/i });
    const west = screen.getByRole("table", { name: /west division standings/i });
    expect(
      within(east)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["1", "2", "3"]);
    expect(
      within(west)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["4", "5", "6"]);
    // Division tables keep the overall-only weekly VP detail off their columns.
    expect(
      within(east).queryByRole("columnheader", { name: /Week \d+ VP/ }),
    ).not.toBeInTheDocument();
    expect(within(east).getAllByRole("columnheader")).toHaveLength(6);
    expect(within(west).queryByRole("columnheader", { name: /^W\d+$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /cumulative victory points/i })).toBeInTheDocument();
    expect(
      screen.getByText(/2026 season · 6 teams · 2 divisions · 4 completed weeks/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Playoff designation legend" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Z — top seed" })).toHaveLength(3);
    expect(screen.getAllByRole("img", { name: "Y — division winner" })).toHaveLength(3);
    expect(screen.getAllByRole("img", { name: "X — clinched playoff berth" })).toHaveLength(5);
    expect(screen.getAllByRole("img", { name: "E — eliminated" })).toHaveLength(5);
    expect(screen.getByRole("heading", { name: "WAPDate standings" })).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /weeks 5-8 · in progress/i })).toBeChecked();
  });

  it("omits the section subheader copy and the decimal footer", async () => {
    readyFetch();
    renderPage();

    await screen.findByRole("table", { name: /overall 2026 standings/i });

    expect(screen.queryByText(/Select a team to highlight/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Each division groups the same teams/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/One line per team\. Series differ by color/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/points arrive from the API as decimal strings/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Standings are computed from synced ESPN data/i),
    ).not.toBeInTheDocument();
    // The headings, meta line, tables, and chart remain.
    expect(screen.getByRole("heading", { name: "Overall standings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Division standings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cumulative VP by week" })).toBeInTheDocument();
    expect(
      screen.getByText(/2026 season · 6 teams · 2 divisions · 4 completed weeks/i),
    ).toBeInTheDocument();
  });

  it("places playoff odds below the WAPDate standings", async () => {
    readyFetch();
    renderPage();

    await screen.findByRole("heading", { level: 2, name: "WAPDate standings" });
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent ?? "");
    expect(headings).toEqual([
      "Overall standings",
      "Division standings",
      "Cumulative VP by week",
      "WAPDate standings",
      "Playoff odds",
    ]);
  });

  it("hides the WAPDate section without requesting it when the league turned it off", async () => {
    const paths: string[] = [];
    mockFetch((url) => {
      const path = requestPath(url);
      paths.push(path);
      if (path.endsWith("/standings")) {
        return jsonResponse(standingsResponse);
      }
      if (path.endsWith("/vp-history")) {
        return jsonResponse(historyResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return errorResponse(404, { code: "not_found", message: "Not found" });
    });

    renderPage(
      contextValue({
        leagues: [{ ...leagueAlpha, show_wapdate: false }],
        selectedLeague: { ...leagueAlpha, show_wapdate: false },
      }),
    );

    await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(
      screen.queryByRole("heading", { level: 2, name: "WAPDate standings" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /WAPDate standings/i })).not.toBeInTheDocument();
    expect(paths.some((path) => path.endsWith("/wapdate"))).toBe(false);
    // The other sections stay in place.
    expect(screen.getByRole("heading", { level: 2, name: "Cumulative VP by week" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "Playoff odds" })).toBeVisible();
  });

  it("hides playoff odds for a prior season without requesting them", async () => {
    const paths: string[] = [];
    mockFetch((url) => {
      const path = requestPath(url);
      paths.push(path);
      if (path.endsWith("/standings")) {
        return jsonResponse(standingsResponse);
      }
      if (path.endsWith("/vp-history")) {
        return jsonResponse(historyResponse);
      }
      if (path.endsWith("/wapdate")) {
        return jsonResponse(wapdateResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return errorResponse(404, { code: "not_found", message: "Not found" });
    });

    renderPage(contextValue({ seasons: [2025, 2026], season: 2025 }));

    await screen.findByRole("heading", { level: 2, name: "WAPDate standings" });
    expect(
      screen.queryByRole("heading", { level: 2, name: "Playoff odds" }),
    ).not.toBeInTheDocument();
    expect(paths.some((path) => path.includes("/seasons/2025/standings"))).toBe(true);
    expect(paths.some((path) => path.endsWith("/playoff-odds"))).toBe(false);
  });

  it("keeps a simulation run local to the odds endpoint (AC-PO-13)", async () => {
    const urls: string[] = [];
    mockFetch((url) => {
      urls.push(String(url));
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse(standingsResponse);
      }
      if (path.endsWith("/vp-history")) {
        return jsonResponse(historyResponse);
      }
      if (path.endsWith("/wapdate")) {
        return jsonResponse(wapdateResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return errorResponse(404, { code: "not_found", message: "Not found" });
    });
    const value = contextValue();
    const user = userEvent.setup();
    renderPage(value);

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    const counts = (suffix: string) =>
      urls.filter((url) => requestPath(url).endsWith(suffix)).length;
    const before = {
      standings: counts("/standings"),
      history: counts("/vp-history"),
      wapdate: counts("/wapdate"),
      odds: counts("/playoff-odds"),
    };

    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.type(screen.getByLabelText("Team strength weight"), ".25");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(
        urls.some(
          (url) =>
            requestPath(url).endsWith("/playoff-odds") &&
            new URL(url).searchParams.get("strength_weight") === ".25",
        ),
      ).toBe(true);
    });

    expect(counts("/standings")).toBe(before.standings);
    expect(counts("/vp-history")).toBe(before.history);
    expect(counts("/wapdate")).toBe(before.wapdate);
    expect(counts("/playoff-odds")).toBe(before.odds + 1);
    expect(urls.some((url) => url.includes("/refresh"))).toBe(false);
    expect(urls.some((url) => /\/(provider|sync)/.test(new URL(url).pathname))).toBe(false);
    expect(value.notifyDataChanged).not.toHaveBeenCalled();
    expect(value.reloadLeagues).not.toHaveBeenCalled();
    expect(value.reloadSeasons).not.toHaveBeenCalled();
    expect(value.selectLeague).not.toHaveBeenCalled();
    expect(value.selectSeason).not.toHaveBeenCalled();
    expect(value.dataVersion).toBe(0);
  });

  it("shows W-L-T when a team recorded an H2H tie", async () => {
    const tied = {
      ...standingsResponse,
      overall: standingsResponse.overall.map((row, index) =>
        index === 0 ? { ...row, ties: 1 } : row,
      ),
    };
    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse(tied);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return path.endsWith("/wapdate")
        ? jsonResponse(wapdateResponse)
        : jsonResponse(historyResponse);
    });
    renderPage();
    const overall = await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(within(overall).getByRole("columnheader", { name: "W-L-T" })).toBeInTheDocument();
    expect(within(overall).getByText("4-0-1")).toBeInTheDocument();
  });

  it("highlights the selected team in both the table and the chart", async () => {
    readyFetch();
    const user = userEvent.setup();
    const { container } = renderPage();
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    const alpha = screen.getAllByRole("button", { name: "Alpha" })[0];
    await user.click(alpha);
    expect(alpha).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('polyline[data-team-id="7"]')).toHaveAttribute(
      "stroke-width",
      "3.2",
    );
  });

  it("toggles a chart series off and back on from the legend", async () => {
    readyFetch();
    const user = userEvent.setup();
    const { container } = renderPage();
    await screen.findByRole("img", { name: /cumulative victory points/i });
    const chip = screen.getByRole("button", { name: "Bravo 8.83" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelector('polyline[data-team-id="3"]')).not.toBeInTheDocument();
    await user.click(chip);
    expect(container.querySelector('polyline[data-team-id="3"]')).toBeInTheDocument();
  });

  it("shows only the double-clicked team in the chart and updates every chip", async () => {
    readyFetch();
    const user = userEvent.setup();
    const { container } = renderPage();
    await screen.findByRole("img", { name: /cumulative victory points/i });

    const bravo = screen.getByRole("button", { name: "Bravo 8.83" });
    await user.dblClick(bravo);

    expect(bravo).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('polyline[data-team-id="3"]')).toBeInTheDocument();
    for (const teamId of [7, 9, 2, 5, 4]) {
      expect(container.querySelector(`polyline[data-team-id="${teamId}"]`)).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Alpha 10.83" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("shows loading, empty, and error states for every data view", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderPage();
    expect(screen.getAllByRole("status")).toHaveLength(5);
    loading.unmount();

    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse(emptyStandingsResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(emptyPlayoffOddsResponse);
      }
      return path.endsWith("/wapdate")
        ? jsonResponse(emptyWapdateResponse)
        : jsonResponse(emptyHistoryResponse);
    });
    const empty = renderPage();
    await screen.findByText("No chart yet");
    expect(screen.getAllByText("No completed weeks yet")).toHaveLength(3);
    expect(screen.getByText("No WAPDate periods yet")).toBeInTheDocument();
    empty.unmount();

    mockFetch(() => errorResponse(500, { code: "boom", message: "The API is unavailable." }));
    renderPage();
    await waitFor(() => {
      expect(screen.getAllByRole("alert")).toHaveLength(5);
    });
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("The API is unavailable.");
  });

  it("retries a failed load", async () => {
    let standingsCalls = 0;
    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/wapdate")) {
        return jsonResponse(wapdateResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return errorResponse(500, { code: "boom", message: "Boom" });
      }
      if (!path.endsWith("/standings")) {
        return jsonResponse(historyResponse);
      }
      standingsCalls += 1;
      return standingsCalls === 1
        ? errorResponse(500, { code: "boom", message: "Boom" })
        : jsonResponse(standingsResponse);
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getAllByRole("alert")).toHaveLength(4);
    });
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() => {
      expect(screen.getByRole("table", { name: /overall 2026 standings/i })).toBeInTheDocument();
    });
  });

  it("explains league and season errors and empty notices", () => {
    mockFetch(() => new Promise<Response>(() => {}));

    const leaguesError = renderPage(contextValue({ leaguesStatus: "error", leaguesError: null }));
    expect(screen.getByRole("alert")).toHaveTextContent("Check your connection and try again.");
    leaguesError.unmount();

    const noLeagues = renderPage(contextValue({ leagues: [], selectedLeague: null }));
    expect(screen.getByText("No leagues yet")).toBeInTheDocument();
    noLeagues.unmount();

    const seasonsError = renderPage(contextValue({ seasonsStatus: "error", seasonsError: null }));
    expect(screen.getByRole("alert")).toHaveTextContent("Check your connection and try again.");
    seasonsError.unmount();

    renderPage(contextValue({ season: null }));
    expect(screen.getByText("No seasons yet")).toBeInTheDocument();
  });

  it("handles unnamed divisions and a season with no completed weeks", async () => {
    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse({
          ...standingsResponse,
          divisions: [{ name: null, standings: standingsResponse.overall }],
        });
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return path.endsWith("/wapdate")
        ? jsonResponse(wapdateResponse)
        : jsonResponse(historyResponse);
    });
    const unnamed = renderPage();
    expect(await screen.findByText("Division 1")).toBeInTheDocument();
    unnamed.unmount();

    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse({ ...standingsResponse, divisions: [] });
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return path.endsWith("/wapdate")
        ? jsonResponse(wapdateResponse)
        : jsonResponse(historyResponse);
    });
    const noDivisions = renderPage();
    expect(await screen.findByText("No divisions")).toBeInTheDocument();
    noDivisions.unmount();

    mockFetch((url) => {
      const path = requestPath(url);
      if (path.endsWith("/standings")) {
        return jsonResponse(standingsResponse);
      }
      if (path.endsWith("/playoff-odds")) {
        return jsonResponse(playoffOddsResponse);
      }
      return path.endsWith("/wapdate")
        ? jsonResponse(wapdateResponse)
        : jsonResponse(emptyHistoryResponse);
    });
    renderPage();
    expect(await screen.findByText("No chart yet")).toBeInTheDocument();
  });
});
