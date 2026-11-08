import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TradeConfigResponse } from "../api/types";
import {
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";
import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import { TradeTrackerSection } from "./TradeTrackerSection";

const sampleTradeConfig: TradeConfigResponse = {
  league_id: 1,
  enabled: true,
  base_auction_budget: "200.00",
  repo_owner: "bberk",
  repo_name: "whodat-trades",
  branch: "main",
  has_github_token: true,
  discord_channel_id: "1234567890",
  team_aliases: {
    alice_discord: "Team Alice",
  },
  last_sync_status: "success",
  last_synced_at: "2026-11-07T12:00:00Z",
  last_sync_commit: "abc1234567890",
  last_sync_error: null,
  discord_sync_status: "idle",
  last_discord_sync_at: "2026-11-07T12:05:00Z",
  last_discord_sync_error: null,
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

function renderSection(value: LeagueContextValue = leagueValue()) {
  return render(
    <LeagueContext.Provider value={value}>
      <TradeTrackerSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TradeTrackerSection", () => {
  it("renders loading state then displays loaded config", async () => {
    mockFetch((url) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        return jsonResponse(sampleTradeConfig);
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection();
    expect(screen.getByText("Loading trade tracker configuration...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByLabelText("Base starting auction budget ($)")).toHaveValue("200.00");
    });

    expect(screen.getByLabelText("GitHub Repo Owner")).toHaveValue("bberk");
    expect(screen.getByLabelText("GitHub Repo Name")).toHaveValue("whodat-trades");
    expect(screen.getByLabelText("Discord #trades Channel ID")).toHaveValue("1234567890");
    expect(screen.getByText("alice_discord")).toBeInTheDocument();
    expect(screen.getByText("Team Alice")).toBeInTheDocument();
    expect(screen.getByText(/Commit:\s*abc1234/)).toBeInTheDocument();
  });

  it("handles loading error and allows retry", async () => {
    let callCount = 0;
    mockFetch((url) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        callCount++;
        if (callCount === 1) {
          return errorResponse(500, { code: "server_error", message: "Failed to load config" });
        }
        return jsonResponse(sampleTradeConfig);
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection();
    await waitFor(() => {
      expect(screen.getByText("Failed to load config")).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole("button", { name: "Retry" });
    await userEvent.setup().click(retryBtn);

    await waitFor(() => {
      expect(screen.getByLabelText("GitHub Repo Owner")).toHaveValue("bberk");
    });
  });

  it("saves updated trade settings and notifies league context", async () => {
    const user = userEvent.setup();
    const contextVal = leagueValue();
    let putBody: Record<string, unknown> | null = null;

    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        if (init?.method === "PUT") {
          putBody = requestBody(init);
          return jsonResponse({
            ...sampleTradeConfig,
            base_auction_budget: "250.00",
            enabled: false,
          });
        }
        return jsonResponse(sampleTradeConfig);
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection(contextVal);
    await waitFor(() => {
      expect(screen.getByLabelText("Base starting auction budget ($)")).toHaveValue("200.00");
    });

    // Change budget
    const budgetInput = screen.getByLabelText("Base starting auction budget ($)");
    await user.clear(budgetInput);
    await user.type(budgetInput, "250.00");

    // Toggle to Disabled
    const disabledRadio = screen.getByRole("radio", { name: "Disabled" });
    await user.click(disabledRadio);

    // Click Save
    const saveBtn = screen.getByRole("button", { name: "Save Trade Settings" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText("Trade tracker configuration saved.")).toBeInTheDocument();
    });

    expect(putBody).toMatchObject({
      base_auction_budget: "250.00",
      enabled: false,
    });
    expect(contextVal.upsertLeague).toHaveBeenCalledWith(
      expect.objectContaining({
        league_id: 1,
        has_trades_enabled: false,
      }),
    );
  });

  it("adds and removes team aliases", async () => {
    const user = userEvent.setup();
    mockFetch((url) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        return jsonResponse(sampleTradeConfig);
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection();
    await waitFor(() => {
      expect(screen.getByText("alice_discord")).toBeInTheDocument();
    });

    // Add new alias
    const aliasInput = screen.getByPlaceholderText("Alias (e.g. alice_discord)");
    const teamInput = screen.getByPlaceholderText("Canonical Team Name / ID");
    const addBtn = screen.getByRole("button", { name: "Add Alias" });

    await user.type(aliasInput, "bob_discord");
    await user.type(teamInput, "Team Bob");
    await user.click(addBtn);

    expect(screen.getByText("bob_discord")).toBeInTheDocument();
    expect(screen.getByText("Team Bob")).toBeInTheDocument();

    // Remove existing alias
    const deleteButtons = screen.getAllByRole("button", { name: "Delete" });
    await user.click(deleteButtons[0]);

    expect(screen.queryByText("alice_discord")).not.toBeInTheDocument();
  });

  it("handles repository sync and displays result banner", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        return jsonResponse(sampleTradeConfig);
      }
      if (requestPath(url) === "/api/v1/leagues/1/trades/sync" && init?.method === "POST") {
        return jsonResponse({
          league_id: 1,
          trades_synced: 3,
          commit_sha: "1234567890abcdef",
          synced_at: "2026-11-07T19:00:00Z",
        });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync Trade Repo" })).toBeEnabled();
    });

    const syncBtn = screen.getByRole("button", { name: "Sync Trade Repo" });
    await user.click(syncBtn);

    await waitFor(() => {
      expect(
        screen.getByText("Successfully synced 3 trade(s) (commit 1234567)."),
      ).toBeInTheDocument();
    });
  });

  it("handles discord trade sync trigger and displays result banner", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/trade-config") {
        return jsonResponse(sampleTradeConfig);
      }
      if (requestPath(url) === "/api/v1/leagues/1/trades/discord-sync" && init?.method === "POST") {
        return jsonResponse({
          league_id: 1,
          status: "accepted",
          message: "Discord trade sync job started in background.",
        });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    renderSection();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync Discord Trades" })).toBeEnabled();
    });

    const syncBtn = screen.getByRole("button", { name: "Sync Discord Trades" });
    await user.click(syncBtn);

    await waitFor(() => {
      expect(screen.getByText("Discord trade sync job started in background.")).toBeInTheDocument();
    });
  });
});
