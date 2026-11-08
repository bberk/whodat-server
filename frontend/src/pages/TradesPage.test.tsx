import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/endpoints";
import type { AuctionBudgetsResponse, TradesListResponse } from "../api/types";
import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { LeagueContextValue } from "../leagues/LeagueContext";
import { LeagueContext } from "../leagues/LeagueContext";
import { adminUser, leagueAlpha, memberUser } from "../test/fixtures";
import { TradesPage } from "./TradesPage";

const sampleTradesResponse: TradesListResponse = {
  league_id: 1,
  trades: [
    {
      id: 1,
      external_trade_id: "trade-2027-1",
      trade_date: "2026-11-07T16:00:00Z",
      agreement_season: 2026,
      is_settled: false,
      discord_url: "https://discord.com/channels/1/2/3",
      summary: "Mahomes for Jefferson + $5 in 2027",
      conditions: [
        {
          id: "c1",
          description: "If Mahomes MVP, Bob pays $5 in 2027",
          draft_year: 2027,
          paying_team: "Team Bob",
          receiving_team: "Team Alice",
          amount: "5.00",
          status: "fulfilled",
        },
      ],
      parties: [
        {
          id: 1,
          owner_id: 1,
          franchise_key: null,
          team_name_raw: "Team Alice",
          players_sent: [{ name: "Patrick Mahomes", position: "QB" }],
          players_received: [{ name: "Justin Jefferson", position: "WR" }],
          draft_picks_sent: [],
          draft_picks_received: [],
          auction_dollars: [{ draft_year: 2027, amount: "-5.00" }],
        },
        {
          id: 2,
          owner_id: 2,
          franchise_key: null,
          team_name_raw: "Team Bob",
          players_sent: [{ name: "Justin Jefferson", position: "WR" }],
          players_received: [{ name: "Patrick Mahomes", position: "QB" }],
          draft_picks_sent: [],
          draft_picks_received: [],
          auction_dollars: [{ draft_year: 2027, amount: "5.00" }],
        },
      ],
    },
  ],
};

const sampleBudget2026: AuctionBudgetsResponse = {
  league_id: 1,
  draft_year: 2026,
  base_auction_budget: "200.00",
  projections: [
    {
      team_id: "Team Alice",
      starting_budget: "200.00",
      base_trade_delta: "0.00",
      fulfilled_conditional_delta: "0.00",
      net_delta: "0.00",
      projected_budget: "200.00",
      pending_conditional_delta: "0.00",
      is_negative_budget: false,
    },
    {
      team_id: "Team Bob",
      starting_budget: "200.00",
      base_trade_delta: "0.00",
      fulfilled_conditional_delta: "0.00",
      net_delta: "0.00",
      projected_budget: "200.00",
      pending_conditional_delta: "0.00",
      is_negative_budget: false,
    },
  ],
};

const sampleBudget2027: AuctionBudgetsResponse = {
  league_id: 1,
  draft_year: 2027,
  base_auction_budget: "200.00",
  projections: [
    {
      team_id: "Team Alice",
      starting_budget: "200.00",
      base_trade_delta: "-5.00",
      fulfilled_conditional_delta: "5.00",
      net_delta: "0.00",
      projected_budget: "200.00",
      pending_conditional_delta: "0.00",
      is_negative_budget: false,
    },
    {
      team_id: "Team Bob",
      starting_budget: "200.00",
      base_trade_delta: "5.00",
      fulfilled_conditional_delta: "-5.00",
      net_delta: "0.00",
      projected_budget: "200.00",
      pending_conditional_delta: "0.00",
      is_negative_budget: false,
    },
  ],
};

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
  leagueCtx: LeagueContextValue = leagueValue(),
  path = "/leagues/1/trades",
  authCtx: AuthContextValue = authValue(),
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={authCtx}>
        <LeagueContext.Provider value={leagueCtx}>
          <Routes>
            <Route path="/leagues/:leagueId/trades" element={<TradesPage />} />
            <Route path="/" element={<p>Home stub</p>} />
          </Routes>
        </LeagueContext.Provider>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe("TradesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state then renders trade feed and auction table", async () => {
    vi.spyOn(api, "listTrades").mockResolvedValue(sampleTradesResponse);
    vi.spyOn(api, "auctionBudgets").mockResolvedValue(sampleBudget2026);

    renderPage();

    expect(screen.getByText("Loading trade and auction budget data...")).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Trades & Auction Budgets" }),
    ).toBeInTheDocument();

    expect(screen.getByText("Alpha League")).toBeInTheDocument();
    expect(screen.getByText("#trade-2027-1")).toBeInTheDocument();
    expect(screen.getByText("Mahomes for Jefferson + $5 in 2027")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Projected Auction Dollars — 2026 Draft" }),
    ).toBeInTheDocument();
  });

  it("renders empty state when no trades exist", async () => {
    vi.spyOn(api, "listTrades").mockResolvedValue({ league_id: 1, trades: [] });
    vi.spyOn(api, "auctionBudgets").mockResolvedValue(sampleBudget2026);

    renderPage();

    expect(await screen.findByText("No trades recorded")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No trades have been synced from Discord or the trade repository yet. Check back once trades are announced and approved.",
      ),
    ).toBeInTheDocument();
  });

  it("renders error state when loading fails and retries on click", async () => {
    const listSpy = vi
      .spyOn(api, "listTrades")
      .mockRejectedValueOnce(new Error("Network failed"))
      .mockResolvedValueOnce(sampleTradesResponse);
    vi.spyOn(api, "auctionBudgets").mockResolvedValue(sampleBudget2026);

    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Network failed")).toBeInTheDocument();

    const retryBtn = screen.getByRole("button", { name: "Retry" });
    await user.click(retryBtn);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Trades & Auction Budgets" }),
    ).toBeInTheDocument();
    expect(listSpy).toHaveBeenCalledTimes(2);
  });

  it("switches draft years when clicking a draft year tab", async () => {
    vi.spyOn(api, "listTrades").mockResolvedValue(sampleTradesResponse);
    const budgetSpy = vi.spyOn(api, "auctionBudgets").mockImplementation((_leagueId, draftYear) => {
      if (draftYear === 2027) return Promise.resolve(sampleBudget2027);
      return Promise.resolve(sampleBudget2026);
    });

    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { level: 1, name: "Trades & Auction Budgets" });

    // Click 2027 tab
    const tab2027 = screen.getByRole("tab", { name: "2027 Draft" });
    await user.click(tab2027);

    expect(budgetSpy).toHaveBeenCalledWith(1, 2027);
    expect(
      await screen.findByRole("heading", { name: "Projected Auction Dollars — 2027 Draft" }),
    ).toBeInTheDocument();
  });

  it("shows admin sync button for admin and triggers trade sync", async () => {
    vi.spyOn(api, "listTrades").mockResolvedValue(sampleTradesResponse);
    vi.spyOn(api, "auctionBudgets").mockResolvedValue(sampleBudget2026);
    const syncSpy = vi.spyOn(api, "syncTradeRepo").mockResolvedValue({
      league_id: 1,
      status: "success",
      trades_synced: 3,
      commit_sha: "abcd123",
      synced_at: "2026-11-07T18:00:00Z",
    });

    const user = userEvent.setup();
    renderPage();

    const syncBtn = await screen.findByRole("button", { name: "Sync Trades from GitHub" });
    expect(syncBtn).toBeInTheDocument();

    await user.click(syncBtn);
    expect(syncSpy).toHaveBeenCalledWith(1);

    expect(
      await screen.findByText("Successfully synced 3 trades from GitHub repository."),
    ).toBeInTheDocument();

    // Dismiss notification
    const dismissBtn = screen.getByRole("button", { name: "Dismiss" });
    await user.click(dismissBtn);
    expect(
      screen.queryByText("Successfully synced 3 trades from GitHub repository."),
    ).not.toBeInTheDocument();
  });

  it("does not show admin sync button for non-admin members", async () => {
    vi.spyOn(api, "listTrades").mockResolvedValue(sampleTradesResponse);
    vi.spyOn(api, "auctionBudgets").mockResolvedValue(sampleBudget2026);

    renderPage(leagueValue(), "/leagues/1/trades", authValue({ user: memberUser }));

    await screen.findByRole("heading", { level: 1, name: "Trades & Auction Budgets" });

    expect(
      screen.queryByRole("button", { name: "Sync Trades from GitHub" }),
    ).not.toBeInTheDocument();
  });

  it("redirects to home if league id is invalid", () => {
    renderPage(leagueValue(), "/leagues/invalid/trades");
    expect(screen.getByText("Home stub")).toBeInTheDocument();
  });
});
