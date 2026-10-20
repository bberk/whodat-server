import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import {
  emptyHistoryResponse,
  emptyStandingsResponse,
  errorResponse,
  historyResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestPath,
  standingsResponse,
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
    upsertLeague: vi.fn(),
    reloadLeagues: vi.fn(),
    dataVersion: 0,
    notifyDataChanged: vi.fn(),
    ...overrides,
  };
}

function renderPage(value: LeagueContextValue = contextValue()) {
  return render(
    <LeagueContext.Provider value={value}>
      <StandingsPage />
    </LeagueContext.Provider>,
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
    return errorResponse(404, { code: "not_found", message: "Not found" });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StandingsPage", () => {
  it("renders the overall table, one table per division, the chart, and the weekly breakdown", async () => {
    const user = userEvent.setup();
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
    expect(screen.getByRole("img", { name: /cumulative victory points/i })).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: /week 4 victory points per team/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 completed weeks/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "W1" }));
    expect(
      await screen.findByRole("table", { name: /week 1 victory points per team/i }),
    ).toBeInTheDocument();
  });

  it("shows W-L-T when a team recorded an H2H tie", async () => {
    const tied = {
      ...standingsResponse,
      overall: standingsResponse.overall.map((row, index) =>
        index === 0 ? { ...row, ties: 1 } : row,
      ),
    };
    mockFetch((url) =>
      requestPath(url).endsWith("/standings") ? jsonResponse(tied) : jsonResponse(historyResponse),
    );
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

  it("shows loading, empty, and error states for every data view", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderPage();
    expect(screen.getAllByRole("status")).toHaveLength(4);
    loading.unmount();

    mockFetch((url) =>
      requestPath(url).endsWith("/standings")
        ? jsonResponse(emptyStandingsResponse)
        : jsonResponse(emptyHistoryResponse),
    );
    const empty = renderPage();
    await screen.findByText("No chart yet");
    expect(screen.getAllByText("No completed weeks yet")).toHaveLength(2);
    expect(screen.getByText("No weekly VP yet")).toBeInTheDocument();
    empty.unmount();

    mockFetch(() => errorResponse(500, { code: "boom", message: "The API is unavailable." }));
    renderPage();
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(4);
    expect(alerts[0]).toHaveTextContent("The API is unavailable.");
  });

  it("retries a failed load", async () => {
    let standingsCalls = 0;
    mockFetch((url) => {
      if (!requestPath(url).endsWith("/standings")) {
        return jsonResponse(historyResponse);
      }
      standingsCalls += 1;
      return standingsCalls === 1
        ? errorResponse(500, { code: "boom", message: "Boom" })
        : jsonResponse(standingsResponse);
    });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findAllByRole("alert")).toHaveLength(4);
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
    mockFetch((url) =>
      requestPath(url).endsWith("/standings")
        ? jsonResponse({
            ...standingsResponse,
            divisions: [{ name: null, standings: standingsResponse.overall }],
          })
        : jsonResponse(historyResponse),
    );
    const unnamed = renderPage();
    expect(await screen.findByText("Division 1")).toBeInTheDocument();
    unnamed.unmount();

    mockFetch((url) =>
      requestPath(url).endsWith("/standings")
        ? jsonResponse({ ...standingsResponse, divisions: [] })
        : jsonResponse(historyResponse),
    );
    const noDivisions = renderPage();
    expect(await screen.findByText("No divisions")).toBeInTheDocument();
    noDivisions.unmount();

    mockFetch((url) =>
      requestPath(url).endsWith("/standings")
        ? jsonResponse(standingsResponse)
        : jsonResponse(emptyHistoryResponse),
    );
    renderPage();
    expect(await screen.findByText("No chart yet")).toBeInTheDocument();
    expect(screen.getByText("No weekly VP yet")).toBeInTheDocument();
  });
});
