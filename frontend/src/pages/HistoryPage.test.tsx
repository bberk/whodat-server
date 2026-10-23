import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import {
  adminUser,
  eloHistoryResponse,
  emptyEloHistoryResponse,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  memberUser,
  mockFetch,
  requestPath,
} from "../test/fixtures";
import { HistoryPage } from "./HistoryPage";

function leagueValue(overrides: Partial<LeagueContextValue> = {}): LeagueContextValue {
  return {
    leagues: [leagueAlpha],
    leaguesStatus: "ready",
    leaguesError: null,
    selectedLeague: leagueAlpha,
    selectLeague: vi.fn(),
    seasons: [2025, 2026],
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
  path = "/leagues/1/history",
  auth: AuthContextValue = authValue(),
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={auth}>
        <LeagueContext.Provider value={value}>
          <Routes>
            <Route path="/leagues/:leagueId/history" element={<HistoryPage />} />
            <Route path="/leagues/:leagueId/admin" element={<p>Admin stub</p>} />
            <Route path="/" element={<p>Standings stub</p>} />
          </Routes>
        </LeagueContext.Provider>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

function eloFetch(handler?: (path: string, mode: string | null) => Response | Promise<Response>) {
  return mockFetch((url) => {
    const path = requestPath(url);
    const mode = new URL(url).searchParams.get("mode");
    if (handler !== undefined) {
      return handler(path, mode);
    }
    if (path === "/api/v1/leagues/1/elo-history") {
      return jsonResponse({
        ...eloHistoryResponse,
        mode: mode === "actual_schedule" ? "actual_schedule" : "round_robin",
      });
    }
    return errorResponse(404, { code: "not_found", message: path });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HistoryPage", () => {
  it("renders the chart summary, legend, cup marker, and current scores table", async () => {
    eloFetch();
    renderPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Alpha League — history" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All history" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Round robin" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const chart = screen.getByRole("img", { name: /Elo score history, Round robin/i });
    expect(chart).toBeInTheDocument();
    expect(chart.getAttribute("aria-label")).toContain("Alpha leads at 1525.20");
    expect(chart.getAttribute("aria-label")).toContain("Cup weeks are marked and count");

    const table = screen.getByRole("region", {
      name: "Elo score history current scores, scrollable horizontally",
    });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    // Sorted by current Elo descending: Alpha 1525.2, Charlie 1512.6, Bravo 1474.8.
    expect(within(rows[1]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(within(rows[2]).getByRole("button", { name: "Charlie" })).toBeInTheDocument();
    expect(within(rows[3]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("1525")).toBeInTheDocument();
    expect(within(rows[1]).getByText("+12.60")).toBeInTheDocument();
    expect(within(rows[1]).getByText("+16.80")).toBeInTheDocument();
    expect(within(rows[3]).getByText("1475")).toBeInTheDocument();
    expect(within(rows[3]).getByText("-12.60")).toBeInTheDocument();

    // The data-table alternative carries the exact values, the gap, and the cup-week header.
    await userEvent.setup().click(screen.getByText("View chart data as a table"));
    const data = screen.getByRole("region", { name: "Elo score history data table" });
    expect(within(data).getByRole("columnheader", { name: "2025 W2 (cup)" })).toBeInTheDocument();
    const alphaRow = within(data).getByRole("row", { name: /Alpha/ });
    expect(within(alphaRow).getAllByRole("cell")[0]).toHaveTextContent("1512.60");
    const charlieRow = within(data).getByRole("row", { name: /Charlie/ });
    expect(within(charlieRow).getAllByRole("cell")[0]).toHaveTextContent("—");
    expect(screen.getByText(/have no rated matchups yet/i)).toBeInTheDocument();
  });

  it("switches modes and refetches the history", async () => {
    const requestedModes: (string | null)[] = [];
    eloFetch((path, mode) => {
      if (path === "/api/v1/leagues/1/elo-history") {
        requestedModes.push(mode);
        return jsonResponse({ ...eloHistoryResponse, mode });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("img", { name: /Round robin/i });
    await user.click(screen.getByRole("button", { name: "Actual schedule" }));

    expect(
      await screen.findByRole("img", { name: /Elo score history, Actual schedule/i }),
    ).toBeInTheDocument();
    expect(requestedModes).toEqual(["round_robin", "actual_schedule"]);
    expect(screen.getByRole("button", { name: "Actual schedule" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("filters the chart to one season without losing the current table", async () => {
    eloFetch();
    const user = userEvent.setup();
    renderPage();

    const chart = await screen.findByRole("img", { name: /Elo score history/i });
    expect(chart.getAttribute("aria-label")).toContain("2025 week 1 to 2026 week 1");

    await user.click(screen.getByRole("button", { name: "2025" }));

    const filtered = screen.getByRole("img", { name: /Elo score history/i });
    expect(filtered.getAttribute("aria-label")).toContain("2025 week 1 to 2025 week 2");
    expect(screen.getByRole("button", { name: "2025" })).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("region", {
        name: "Elo score history current scores, scrollable horizontally",
      }),
    ).toBeInTheDocument();
  });

  it("shows warnings and links admins to the settings page", async () => {
    eloFetch((path) =>
      path === "/api/v1/leagues/1/elo-history"
        ? jsonResponse({
            ...eloHistoryResponse,
            warnings: [
              {
                season: 2025,
                code: "missing_score",
                message: "Season 2025, week 2 is missing a score.",
              },
            ],
          })
        : errorResponse(404, { code: "not_found", message: path }),
    );
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Some stored data was skipped:")).toBeInTheDocument();
    expect(screen.getByText("Season 2025, week 2 is missing a score.")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "League admin can change the Elo settings." }),
    );
    expect(screen.getByText("Admin stub")).toBeInTheDocument();
  });

  it("shows an empty state for a season with no rated weeks", async () => {
    eloFetch((path) =>
      path === "/api/v1/leagues/1/elo-history"
        ? jsonResponse({ ...eloHistoryResponse, seasons: [2024, 2025, 2026] })
        : errorResponse(404, { code: "not_found", message: path }),
    );
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("img", { name: /Elo score history/i });
    await user.click(screen.getByRole("button", { name: "2024" }));

    expect(screen.getByText("No rated weeks in this season")).toBeInTheDocument();
  });

  it("hides admin-only text and handles empty unrated lists", async () => {
    eloFetch((path) =>
      path === "/api/v1/leagues/1/elo-history"
        ? jsonResponse({
            ...eloHistoryResponse,
            seasons: [2026],
            unrated_teams: [
              { team_key: "espn:4", name: "Delta", reason: "No rated matchups yet" },
              { team_key: "espn:5", name: "Echo", reason: "No rated matchups yet" },
            ],
          })
        : errorResponse(404, { code: "not_found", message: path }),
    );
    renderPage(leagueValue(), "/leagues/1/history", authValue({ user: memberUser }));

    await screen.findByRole("img", { name: /Elo score history/i });
    expect(screen.queryByText(/League admin can change the Elo settings/)).not.toBeInTheDocument();
    expect(screen.getByText(/2 teams have no rated matchups yet/i)).toBeInTheDocument();
    expect(screen.getByText(/1 season ·/)).toBeInTheDocument();
  });

  it("deselects a team and toggles the same series back on", async () => {
    eloFetch();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("region", {
      name: "Elo score history current scores, scrollable horizontally",
    });
    const alpha = screen.getByRole("button", { name: "Alpha" });
    await user.click(alpha);
    expect(alpha).toHaveAttribute("aria-pressed", "true");
    await user.click(alpha);
    expect(alpha).toHaveAttribute("aria-pressed", "false");

    const toggle = screen.getByRole("button", { name: "Show or hide Bravo series" });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });

  it("selects and toggles chart series", async () => {
    eloFetch();
    const user = userEvent.setup();
    const { container } = renderPage();

    await screen.findByRole("region", {
      name: "Elo score history current scores, scrollable horizontally",
    });
    await user.click(screen.getByRole("button", { name: "Alpha" }));

    expect(screen.getByRole("button", { name: "Alpha" })).toHaveAttribute("aria-pressed", "true");
    const alphaLine = container.querySelector('[data-team-key="espn:1"]');
    expect(alphaLine).toHaveAttribute("stroke-width", "3.4");

    const bravoToggle = screen.getByRole("button", { name: "Show or hide Bravo series" });
    await user.click(bravoToggle);
    expect(bravoToggle).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelector('[data-team-key="espn:2"]')).not.toBeInTheDocument();
  });

  it("shows loading, empty, and error states and retries a failure", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Loading Elo history");
    loading.unmount();

    eloFetch((path) =>
      path === "/api/v1/leagues/1/elo-history"
        ? jsonResponse(emptyEloHistoryResponse)
        : errorResponse(404, { code: "not_found", message: path }),
    );
    const empty = renderPage();
    expect(await screen.findByText("No rated weeks yet")).toBeInTheDocument();
    empty.unmount();

    let calls = 0;
    mockFetch((url) => {
      const path = requestPath(url);
      if (path !== "/api/v1/leagues/1/elo-history") {
        return errorResponse(404, { code: "not_found", message: path });
      }
      calls += 1;
      return calls === 1
        ? errorResponse(500, { code: "boom", message: "Elo is unavailable." })
        : jsonResponse(eloHistoryResponse);
    });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Elo is unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(
        screen.getByRole("region", {
          name: "Elo score history current scores, scrollable horizontally",
        }),
      ).toBeInTheDocument();
    });
  });

  it("selects the league named by the route and redirects an invalid id", () => {
    eloFetch();
    const value = leagueValue({ selectedLeague: { ...leagueAlpha, league_id: 2 } });
    const first = renderPage(value);
    expect(value.selectLeague).toHaveBeenCalledWith(1);
    first.unmount();

    renderPage(leagueValue(), "/leagues/not-a-number/history");
    expect(screen.getByText("Standings stub")).toBeInTheDocument();
  });
});
