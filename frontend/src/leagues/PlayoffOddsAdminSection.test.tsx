import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PlayoffOddsResponse } from "../api/types";
import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import {
  emptyPlayoffOddsResponse,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  playoffOddsResponse,
  requestPath,
} from "../test/fixtures";
import { PlayoffOddsAdminSection } from "./PlayoffOddsAdminSection";

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

function renderSection(value: LeagueContextValue = leagueValue()) {
  return render(
    <LeagueContext.Provider value={value}>
      <PlayoffOddsAdminSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

function oddsFetch(body: PlayoffOddsResponse, urls?: string[]) {
  return mockFetch((url) => {
    urls?.push(url);
    return requestPath(url).endsWith("/playoff-odds")
      ? jsonResponse(body)
      : errorResponse(404, { code: "not_found", message: "Not found" });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlayoffOddsAdminSection", () => {
  it("runs the default simulation for the selected season and shows the table", async () => {
    const urls: string[] = [];
    oddsFetch(playoffOddsResponse, urls);
    const value = leagueValue();
    const user = userEvent.setup();
    renderSection(value);

    expect(
      screen.getByRole("heading", { level: 2, name: "Playoff odds simulation" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2026 — current season")).toBeInTheDocument();
    expect(screen.queryByLabelText("Simulation season")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Simulations")).toHaveValue(10000);
    expect(screen.getByLabelText("Team strength weight")).toHaveValue(1);
    expect(screen.getByLabelText("Seed (optional)")).toHaveValue(null);
    expect(screen.getByText(/does not contact ESPN or refresh stored data/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Team strength weight")).toHaveAttribute(
      "aria-describedby",
      "playoff-odds-strength-weight-hint",
    );
    expect(screen.getByText(/0 makes every remaining matchup even/i)).toBeInTheDocument();
    expect(screen.getByText(/1 is the current model/i)).toBeInTheDocument();
    expect(screen.getByText(/values above 1 overweight stronger teams/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByText(/10,000 simulated seasons/i)).toBeVisible();
    expect(screen.getByText(/seed 1837462/i)).toBeInTheDocument();
    expect(screen.getByText(/strength weight 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Model vp-mc-2:/i)).toBeInTheDocument();
    const table = screen.getByRole("region", {
      name: "Playoff odds, scrollable horizontally",
    });
    expect(within(table).getAllByRole("row")).toHaveLength(playoffOddsResponse.teams.length + 1);
    const requestUrl = new URL(urls[0]);
    expect(requestUrl.pathname).toBe("/api/v1/leagues/1/seasons/2026/playoff-odds");
    expect(requestUrl.searchParams.get("iterations")).toBe("10000");
    expect(requestUrl.searchParams.get("strength_weight")).toBe("1");
    expect(requestUrl.searchParams.has("seed")).toBe(false);
    expect(urls.some((url) => url.includes("/refresh"))).toBe(false);
    expect(value.notifyDataChanged).not.toHaveBeenCalled();
  });

  it("sends a decimal team strength weight to the odds endpoint", async () => {
    const urls: string[] = [];
    oddsFetch(
      { ...playoffOddsResponse, strength_weight: "0.5", input_version: "sha256:even" },
      urls,
    );
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.type(screen.getByLabelText("Team strength weight"), "0.5");
    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByText(/strength weight 0.5/i)).toBeVisible();
    const requestUrl = new URL(urls[0]);
    expect(requestUrl.searchParams.get("strength_weight")).toBe("0.5");
  });

  it("runs only the latest stored season even when an older season is selected", async () => {
    const urls: string[] = [];
    const body: PlayoffOddsResponse = {
      ...playoffOddsResponse,
      iterations: 50_000,
      seed: 42,
    };
    oddsFetch(body, urls);
    const user = userEvent.setup();
    renderSection(leagueValue({ seasons: [2025, 2026], season: 2025 }));

    expect(screen.getByText("2026 — current season")).toBeInTheDocument();
    expect(screen.queryByLabelText("Simulation season")).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Simulations"));
    await user.type(screen.getByLabelText("Simulations"), "50000");
    await user.type(screen.getByLabelText("Seed (optional)"), "42");
    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByText(/50,000 simulated seasons/i)).toBeVisible();
    expect(screen.getByText(/seed 42/i)).toBeInTheDocument();
    const requestUrl = new URL(urls[0]);
    expect(requestUrl.pathname).toBe("/api/v1/leagues/1/seasons/2026/playoff-odds");
    expect(requestUrl.searchParams.get("iterations")).toBe("50000");
    expect(requestUrl.searchParams.get("seed")).toBe("42");
  });

  it.each([
    { label: "iteration", field: "Simulations", value: "999", message: /1,000 to 50,000/ },
    {
      label: "iteration",
      field: "Simulations",
      value: "50001",
      message: /1,000 to 50,000/,
    },
    { label: "seed", field: "Seed (optional)", value: "-1", message: /whole seed/i },
    {
      label: "weight",
      field: "Team strength weight",
      value: "10.1",
      message: /0 to 10, for example 1 or 0.5/,
    },
  ])("rejects an invalid $label before requesting the API", async ({ field, value, message }) => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      return jsonResponse(playoffOddsResponse);
    });
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText(field));
    await user.type(screen.getByLabelText(field), value);
    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(calls).toBe(0);
  });

  it("rejects an empty team strength weight before requesting the API", async () => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      return jsonResponse(playoffOddsResponse);
    });
    const user = userEvent.setup();
    renderSection();

    await user.clear(screen.getByLabelText("Team strength weight"));
    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/0 to 10/);
    expect(calls).toBe(0);
  });

  it("rejects a non-decimal team strength weight", async () => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      return jsonResponse(playoffOddsResponse);
    });
    const user = userEvent.setup();
    renderSection();

    // A number input accepts scientific notation, but the endpoint contract is a plain decimal.
    fireEvent.change(screen.getByLabelText("Team strength weight"), { target: { value: "1e1" } });
    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/0 to 10/);
    expect(calls).toBe(0);
  });

  it("shows the unavailable reason when the season cannot be simulated", async () => {
    oddsFetch({ ...emptyPlayoffOddsResponse, reason: "missing_playoff_field" });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByText("Playoff settings are incomplete")).toBeVisible();
    expect(screen.getByText(/missing or too small for its divisions/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a finished season as exact final seeding", async () => {
    oddsFetch({
      ...playoffOddsResponse,
      iterations: 0,
      seed: null,
      remaining_weeks: [],
      confidence: "normal",
    });
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByText(/Regular season complete · final seeding/i)).toBeVisible();
    expect(screen.queryByText(/simulated seasons/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Playoff odds, scrollable horizontally" }),
    ).toBeInTheDocument();
  });

  it("reports an API failure with its structured message", async () => {
    mockFetch(() => errorResponse(500, { code: "boom", message: "The simulation failed." }));
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Run simulations" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The simulation failed.");
  });

  it("shows the season context states and retries a season load", async () => {
    const reloadSeasons = vi.fn();
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderSection(
      leagueValue({ seasonsStatus: "loading", seasons: [], season: null }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading seasons…");
    loading.unmount();

    const empty = renderSection(leagueValue({ seasonsStatus: "ready", seasons: [], season: null }));
    expect(await screen.findByText("No stored seasons")).toBeInTheDocument();
    empty.unmount();

    mockFetch(() => new Promise<Response>(() => {}));
    renderSection(
      leagueValue({
        seasonsStatus: "error",
        seasonsError: "Could not load seasons.",
        seasons: [],
        season: null,
        reloadSeasons,
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load seasons.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(reloadSeasons).toHaveBeenCalled();
  });

  it("shows a busy state while the simulation runs", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const user = userEvent.setup();
    renderSection();

    const button = screen.getByRole("button", { name: "Run simulations" });
    await user.click(button);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Running 10,000 simulations/ })).toBeDisabled();
    });
  });
});
