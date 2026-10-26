import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MeResponse } from "../api/types";
import type { PlayoffOddsResponse } from "../api/types";
import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import {
  adminUser,
  emptyPlayoffOddsResponse,
  errorResponse,
  jsonResponse,
  memberUser,
  mockFetch,
  playoffOddsResponse,
  requestPath,
} from "../test/fixtures";
import { expectRowDividersAcrossEveryCell } from "../test/tableDividers";
import { PlayoffOddsSection } from "./PlayoffOddsSection";

const REASONS = [
  "no_completed_weeks",
  "missing_playoff_field",
  "incomplete_schedule",
  "unsupported_division_shape",
  "invalid_playoff_bracket",
] as const;

function sectionFetch(body: PlayoffOddsResponse) {
  return mockFetch((url) =>
    requestPath(url).endsWith("/playoff-odds")
      ? jsonResponse(body)
      : errorResponse(404, { code: "not_found", message: "Not found" }),
  );
}

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

function renderSection(user: MeResponse | null = memberUser) {
  return render(
    <AuthContext.Provider value={authValue(user)}>
      <PlayoffOddsSection leagueId={1} season={2026} dataVersion={0} />
    </AuthContext.Provider>,
  );
}

function table() {
  return screen.getByRole("region", { name: "Playoff odds, scrollable horizontally" });
}

function teamNames(): string[] {
  return within(table())
    .getAllByRole("rowheader")
    .map((cell) => cell.querySelector("span")?.textContent ?? "");
}

function lastQuery(fetchMock: ReturnType<typeof sectionFetch>): URLSearchParams {
  const call = fetchMock.mock.calls.at(-1);
  return new URL(String(call?.[0])).searchParams;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlayoffOddsSection (AC-PO-11)", () => {
  it("shows a loading state while the simulation request is pending", () => {
    mockFetch(() => new Promise<Response>(() => {}));
    renderSection();

    expect(screen.getByRole("status")).toHaveTextContent("Simulating 10,000 seasons…");
    expect(screen.getByRole("heading", { name: "Playoff odds" })).toBeInTheDocument();
  });

  it("renders team, division, playoff, bye, and championship odds with intervals", async () => {
    sectionFetch(playoffOddsResponse);
    renderSection();

    const region = await screen.findByRole("region", {
      name: "Playoff odds, scrollable horizontally",
    });
    expect(within(region).getByRole("columnheader", { name: "Team" })).toBeInTheDocument();
    expect(within(region).getByRole("columnheader", { name: "Division" })).toBeInTheDocument();
    expect(within(region).getByRole("columnheader", { name: "Playoff %" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(within(region).getByRole("columnheader", { name: "Bye %" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    expect(within(region).getByRole("columnheader", { name: "Championship %" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    expect(screen.getByText(/10,000 simulated seasons · 95% range shown/i)).toBeInTheDocument();
    expect(screen.getByText(/sorted by Playoff %, high to low/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Based on 4 completed weeks; early-season estimates are wide/i),
    ).toBeVisible();
    expect(screen.getByText("How these are estimated")).toBeInTheDocument();
    expect(screen.getByText(/Real stored playoff matchups are not used/i)).toBeInTheDocument();

    // Default order is playoff probability descending, with the team name as the stable tiebreak.
    expect(teamNames()).toEqual(["Alpha", "Delta", "Bravo", "Foxtrot", "Echo", "Charlie"]);

    const bravo = screen.getByRole("row", { name: /Bravo/ });
    expect(
      within(bravo).getByText(/playoff 84 percent, 95 percent interval 83 percent to 85 percent/i),
    ).toBeInTheDocument();
    expect(within(bravo).getByText(/first-round bye 31 percent/i)).toBeInTheDocument();
    expect(within(bravo).getByText(/division title 0 percent/i)).toBeInTheDocument();
    expect(
      within(bravo).getByText(
        /championship 20 percent, 95 percent interval 19 percent to 21 percent/i,
      ),
    ).toBeInTheDocument();
    expect(within(bravo).getByText("83–85%")).toBeInTheDocument();

    // The bar is decorative; the authoritative values are text and accessible names.
    expect(within(bravo).getByText("84%")).toBeInTheDocument();
    expect(within(bravo).getAllByText("84%")[0]).toBeVisible();
    expect(within(bravo).queryByRole("img")).not.toBeInTheDocument();
  });

  it("paints the row divider across the final column", async () => {
    sectionFetch(playoffOddsResponse);
    renderSection();

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    expectRowDividersAcrossEveryCell(within(table()).getByRole("table"));
  });

  it("sorts by playoff, bye, and championship probability but never by team", async () => {
    sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection();

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    const teamHeader = screen.getByRole("columnheader", { name: "Team" });
    expect(teamHeader).not.toHaveAttribute("aria-sort");
    expect(within(teamHeader).queryByRole("button")).not.toBeInTheDocument();

    const playoffHeader = screen.getByRole("columnheader", { name: "Playoff %" });
    await user.click(screen.getByRole("button", { name: "Sort by Playoff %" }));
    expect(playoffHeader).toHaveAttribute("aria-sort", "ascending");
    expect(teamNames()[0]).toBe("Charlie");

    const byeHeader = screen.getByRole("columnheader", { name: "Bye %" });
    await user.click(screen.getByRole("button", { name: "Sort by Bye %" }));
    expect(byeHeader).toHaveAttribute("aria-sort", "descending");
    expect(teamNames()[0]).toBe("Alpha");
    await user.click(screen.getByRole("button", { name: "Sort by Bye %" }));
    expect(byeHeader).toHaveAttribute("aria-sort", "ascending");
    expect(teamNames()[0]).toBe("Charlie");
    expect(screen.getByText(/sorted by Bye %, low to high/i)).toBeInTheDocument();

    const championshipHeader = screen.getByRole("columnheader", { name: "Championship %" });
    await user.click(screen.getByRole("button", { name: "Sort by Championship %" }));
    expect(championshipHeader).toHaveAttribute("aria-sort", "descending");
    expect(teamNames()[0]).toBe("Alpha");
    expect(screen.getByText(/sorted by Championship %, high to low/i)).toBeInTheDocument();
  });

  it("labels sub-1% and above-99% estimates instead of rounding them to 0% or 100%", async () => {
    const edge: PlayoffOddsResponse = {
      ...playoffOddsResponse,
      teams: playoffOddsResponse.teams.map((team) => {
        if (team.team_name === "Charlie") {
          return {
            ...team,
            playoff: { probability: "0.0030", low: "0.0000", high: "0.0120" },
          };
        }
        if (team.team_name === "Delta") {
          return {
            ...team,
            playoff: { probability: "0.9951", low: "0.9880", high: "0.9980" },
          };
        }
        return team;
      }),
    };
    sectionFetch(edge);
    renderSection();

    const charlie = await screen.findByRole("row", { name: /Charlie/ });
    const delta = screen.getByRole("row", { name: /Delta/ });
    expect(within(charlie).getByText("<1%")).toBeInTheDocument();
    expect(within(delta).getByText(">99%")).toBeInTheDocument();
    expect(within(charlie).getByText(/playoff less than 1 percent/i)).toBeInTheDocument();
    expect(within(delta).getByText(/playoff more than 99 percent/i)).toBeInTheDocument();
  });

  it.each(REASONS)("renders the unavailable copy for %s", async (reason) => {
    sectionFetch({ ...emptyPlayoffOddsResponse, reason });
    renderSection();

    await screen.findByText(
      reason === "no_completed_weeks"
        ? "No completed weeks yet"
        : reason === "missing_playoff_field"
          ? "Playoff settings are incomplete"
          : reason === "incomplete_schedule"
            ? "Remaining schedule is incomplete"
            : reason === "unsupported_division_shape"
              ? "Division setup is not supported"
              : "This playoff field cannot form a bracket",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a finished regular season as a projected bracket", async () => {
    const finished: PlayoffOddsResponse = {
      ...playoffOddsResponse,
      iterations: 10_000,
      confidence: "normal",
      remaining_weeks: [],
      teams: playoffOddsResponse.teams.map((team, index) => ({
        ...team,
        playoff: {
          probability: index < 4 ? "1.0000" : "0.0000",
          low: index < 4 ? "1.0000" : "0.0000",
          high: index < 4 ? "1.0000" : "0.0000",
        },
      })),
    };
    sectionFetch(finished);
    renderSection();

    expect(await screen.findByText(/Regular season complete · projected bracket/i)).toBeVisible();
    expect(screen.getByText(/10,000 simulated seasons/i)).toBeVisible();
    expect(screen.queryByText(/early-season estimates are wide/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("100%")).not.toHaveLength(0);
    expect(screen.getAllByText("0%")).not.toHaveLength(0);
  });

  it("shows an empty table state when no teams are stored", async () => {
    sectionFetch({ ...playoffOddsResponse, teams: [] });
    renderSection();

    expect(await screen.findByText("No teams to show")).toBeVisible();
  });

  it("shows an error and retries the request", async () => {
    let calls = 0;
    mockFetch((url) => {
      if (!requestPath(url).endsWith("/playoff-odds")) {
        return errorResponse(404, { code: "not_found", message: "Not found" });
      }
      calls += 1;
      return calls === 1
        ? errorResponse(500, { code: "boom", message: "The API is unavailable." })
        : jsonResponse(playoffOddsResponse);
    });
    const user = userEvent.setup();
    renderSection();

    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(
        screen.getByRole("region", { name: "Playoff odds, scrollable horizontally" }),
      ).toBeInTheDocument();
    });
  });
});

describe("PlayoffOddsSection controls (AC-PO-19)", () => {
  it("shows the regular-member iteration cap", async () => {
    sectionFetch(playoffOddsResponse);
    renderSection(memberUser);

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    expect(screen.getByText(/Use 1 to 10,000 simulations; 10,000 is the default/i)).toBeVisible();
  });

  it("shows the admin iteration cap", async () => {
    sectionFetch(playoffOddsResponse);
    renderSection(adminUser);

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    expect(screen.getByText(/Use 1 to 100,000 simulations; 10,000 is the default/i)).toBeVisible();
  });

  it("runs with an explicit seed and a weight without a leading zero", async () => {
    const fetchMock = sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection();

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    await user.clear(screen.getByLabelText("Simulations"));
    await user.type(screen.getByLabelText("Simulations"), "2500");
    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.type(screen.getByLabelText("Team strength weight"), ".25");
    await user.type(screen.getByLabelText("Seed (optional)"), "42");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(lastQuery(fetchMock).get("iterations")).toBe("2500");
    });
    const query = lastQuery(fetchMock);
    expect(query.get("strength_weight")).toBe(".25");
    expect(query.get("seed")).toBe("42");
  });

  it("accepts a trailing-dot weight", async () => {
    const fetchMock = sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection();

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.type(screen.getByLabelText("Team strength weight"), "1.");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(lastQuery(fetchMock).get("strength_weight")).toBe("1.");
    });
  });

  it("rejects a non-numeric weight before requesting the API", async () => {
    const fetchMock = sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection();

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    const before = fetchMock.mock.calls.length;
    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.type(screen.getByLabelText("Team strength weight"), "abc");
    await user.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a team strength weight from 0 to 10",
    );
    expect(fetchMock).toHaveBeenCalledTimes(before);
  });

  it("rejects an iteration count above the member cap", async () => {
    const fetchMock = sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection(memberUser);

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    const before = fetchMock.mock.calls.length;
    await user.clear(screen.getByLabelText("Simulations"));
    await user.type(screen.getByLabelText("Simulations"), "10001");
    await user.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a whole number of simulations from 1 to 10,000",
    );
    expect(fetchMock).toHaveBeenCalledTimes(before);
  });

  it("lets an admin run above the member cap", async () => {
    const fetchMock = sectionFetch(playoffOddsResponse);
    const user = userEvent.setup();
    renderSection(adminUser);

    await screen.findByRole("region", { name: "Playoff odds, scrollable horizontally" });
    await user.clear(screen.getByLabelText("Simulations"));
    await user.type(screen.getByLabelText("Simulations"), "10001");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(lastQuery(fetchMock).get("iterations")).toBe("10001");
    });
  });
});
