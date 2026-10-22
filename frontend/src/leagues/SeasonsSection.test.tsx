import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import {
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestBody,
  requestPath,
  seasonSettingsResponse,
} from "../test/fixtures";
import { formatLastRefreshed } from "./formatSeason";
import { SeasonsSection } from "./SeasonsSection";

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
      <SeasonsSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

function settingsResponse(seasons = seasonSettingsResponse.seasons) {
  return jsonResponse({ seasons });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeasonsSection", () => {
  it("renders one row per season with cup-week options, last refreshed, and row actions", async () => {
    mockFetch((url) =>
      requestPath(url) === "/api/v1/leagues/1/seasons/settings"
        ? jsonResponse(seasonSettingsResponse)
        : errorResponse(404, { code: "not_found", message: requestPath(url) }),
    );
    renderSection();

    expect(screen.getByRole("heading", { level: 2, name: "Seasons" })).toBeInTheDocument();
    expect(await screen.findByRole("rowheader", { name: "2025" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "2026" })).toBeInTheDocument();

    const select2025 = screen.getByLabelText("Cup week for 2025");
    expect(select2025).toHaveValue("");
    expect(
      Array.from(select2025.querySelectorAll("option")).map((option) => option.textContent),
    ).toEqual(["No cup week", ...Array.from({ length: 14 }, (_, index) => `Week ${index + 1}`)]);
    expect(screen.getByLabelText("Cup week for 2026")).toHaveValue("1");

    expect(
      screen.getByText(formatLastRefreshed(seasonSettingsResponse.seasons[0].last_refreshed_at)),
    ).toBeInTheDocument();
    expect(screen.getByText("Never")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh season 2025" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete season 2025" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a season" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save cup week/i })).not.toBeInTheDocument();
  });

  it("formats a missing timestamp as Never", () => {
    expect(formatLastRefreshed(null)).toBe("Never");
    expect(formatLastRefreshed("not-a-date")).toBe("Never");
  });

  it("saves a cup-week change immediately and signals the standings to reload", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let putCalls = 0;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path === "/api/v1/leagues/1/seasons/2026/cup-week" && init.method === "PUT") {
        putCalls += 1;
        expect(requestBody(init)).toEqual({ cup_week: 2 });
        return jsonResponse({ season: 2026, cup_week: 2, regular_season_length: 2 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection(value);

    const select = await screen.findByLabelText("Cup week for 2026");
    await user.selectOptions(select, "2");

    expect(await screen.findByText("Cup week saved for 2026.")).toBeInTheDocument();
    expect(select).toHaveValue("2");
    expect(putCalls).toBe(1);
    expect(value.notifyDataChanged).toHaveBeenCalledTimes(1);
  });

  it("shows a per-row saving state and keeps the stored cup week on failure", async () => {
    const user = userEvent.setup();
    let resolvePut: ((response: Response) => void) | undefined;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path.endsWith("/cup-week") && init.method === "PUT") {
        return new Promise<Response>((resolve) => {
          resolvePut = resolve;
        });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    const select = await screen.findByLabelText("Cup week for 2026");
    await user.selectOptions(select, "2");

    expect(select).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeInTheDocument();

    resolvePut?.(
      errorResponse(400, {
        code: "invalid_cup_week",
        message: "cup_week must be between 1 and the season's regular season length",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "cup_week must be between 1 and the season's regular season length",
    );
    expect(select).toHaveValue("1");
    expect(select).toBeEnabled();
  });

  it("refreshes one row, reports progress, and updates its last-refreshed value", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let resolveRefresh: ((response: Response) => void) | undefined;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path === "/api/v1/leagues/1/seasons/2026/refresh" && init.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveRefresh = resolve;
        });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection(value);

    await screen.findByRole("rowheader", { name: "2026" });
    expect(screen.getByText("Never")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Refresh season 2026" });
    await user.click(button);

    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Refreshing…");

    resolveRefresh?.(jsonResponse({ season: 2026, weeks_synced: [1, 2] }));

    expect(await screen.findByText("Refreshed 2 weeks (W1, W2).")).toBeInTheDocument();
    expect(screen.queryByText("Never")).not.toBeInTheDocument();
    expect(value.notifyDataChanged).toHaveBeenCalledTimes(1);
  });

  it("shows the rate-limit message for a rejected refresh", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path.endsWith("/refresh") && init.method === "POST") {
        return errorResponse(
          429,
          { code: "rate_limited", message: "League refresh is rate limited" },
          42,
        );
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    await screen.findByRole("rowheader", { name: "2026" });
    await user.click(screen.getByRole("button", { name: "Refresh season 2026" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 42 seconds");
  });

  it("deletes only the confirmed season and reports success", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let deletedPath: string | null = null;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return jsonResponse(seasonSettingsResponse);
      }
      if (path === "/api/v1/leagues/1/seasons/2025" && init.method === "DELETE") {
        deletedPath = path;
        return new Response(null, { status: 204 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection(value);

    await screen.findByRole("rowheader", { name: "2025" });
    await user.click(screen.getByRole("button", { name: "Delete season 2025" }));

    let dialog = screen.getByRole("dialog", { name: "Delete season 2025?" });
    expect(within(dialog).getByText(/only the 2025 season/i)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deletedPath).toBeNull();

    await user.click(screen.getByRole("button", { name: "Delete season 2025" }));
    dialog = screen.getByRole("dialog", { name: "Delete season 2025?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete season 2025" }));

    expect(await screen.findByText("Season 2025 deleted.")).toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: "2025" })).not.toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "2026" })).toBeInTheDocument();
    expect(deletedPath).toBe("/api/v1/leagues/1/seasons/2025");
    expect(value.reloadSeasons).toHaveBeenCalledTimes(1);
    expect(value.notifyDataChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps the season and shows an error when deletion fails", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path.endsWith("/2026") && init.method === "DELETE") {
        return errorResponse(404, { code: "not_found", message: "League season not found" });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    await screen.findByRole("rowheader", { name: "2026" });
    await user.click(screen.getByRole("button", { name: "Delete season 2026" }));
    const dialog = screen.getByRole("dialog", { name: "Delete season 2026?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete season 2026" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("League season not found");
    expect(screen.getByRole("rowheader", { name: "2026" })).toBeInTheDocument();
  });

  it("adds a season from the + action, selects it, and refetches the rows", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let settingsCalls = 0;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        settingsCalls += 1;
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path === "/api/v1/leagues/1/seasons" && init.method === "POST") {
        expect(requestBody(init)).toEqual({ season: 2024 });
        return jsonResponse({ league_id: 1, season: 2024, weeks_synced: [1] }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection(value);

    await screen.findByRole("rowheader", { name: "2026" });
    await user.click(screen.getByRole("button", { name: "Add a season" }));

    const dialog = screen.getByRole("dialog", { name: "Add a season" });
    const input = within(dialog).getByLabelText("Season year");
    expect(input).toHaveValue(new Date().getFullYear());
    expect(input).toHaveAttribute("min", "2000");
    expect(input).toHaveAttribute("max", "2100");
    expect(input).toBeRequired();

    await user.clear(input);
    await user.type(input, "2024");
    await user.click(within(dialog).getByRole("button", { name: "Add season" }));

    expect(await screen.findByText("Season 2024 added and synced.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(value.addStoredSeason).toHaveBeenCalledWith(2024);
    expect(value.reloadSeasons).toHaveBeenCalledTimes(1);
    expect(value.notifyDataChanged).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(settingsCalls).toBeGreaterThanOrEqual(2);
    });
  });

  it("rejects an empty or out-of-range add year before calling the API", async () => {
    const user = userEvent.setup();
    let postCalls = 0;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path === "/api/v1/leagues/1/seasons" && init.method === "POST") {
        postCalls += 1;
        return jsonResponse({ league_id: 1, season: 2024, weeks_synced: [] }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    await screen.findByRole("rowheader", { name: "2026" });
    await user.click(screen.getByRole("button", { name: "Add a season" }));
    const dialog = screen.getByRole("dialog", { name: "Add a season" });
    const input = within(dialog).getByLabelText("Season year");

    await user.clear(input);
    await user.click(within(dialog).getByRole("button", { name: "Add season" }));
    expect(
      within(dialog).getByText("Enter a whole season year between 2000 and 2100."),
    ).toBeInTheDocument();

    await user.type(input, "1999");
    await user.click(within(dialog).getByRole("button", { name: "Add season" }));
    expect(
      within(dialog).getByText("Season must be a whole year between 2000 and 2100."),
    ).toBeInTheDocument();
    expect(postCalls).toBe(0);
  });

  it("shows a structured error when adding a duplicate season", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/settings") {
        return settingsResponse([seasonSettingsResponse.seasons[1]]);
      }
      if (path === "/api/v1/leagues/1/seasons" && init.method === "POST") {
        return errorResponse(409, {
          code: "season_exists",
          message: "This season already exists for this league",
        });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    await screen.findByRole("rowheader", { name: "2026" });
    await user.click(screen.getByRole("button", { name: "Add a season" }));
    const dialog = screen.getByRole("dialog", { name: "Add a season" });
    await user.click(within(dialog).getByRole("button", { name: "Add season" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This season already exists for this league",
    );
  });

  it("shows loading, empty, and retryable error states", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderSection();
    expect(screen.getByRole("status", { name: "Loading seasons…" })).toBeInTheDocument();
    loading.unmount();

    mockFetch((url) =>
      requestPath(url) === "/api/v1/leagues/1/seasons/settings"
        ? settingsResponse([])
        : errorResponse(404, { code: "not_found", message: "unexpected" }),
    );
    const empty = renderSection();
    expect(await screen.findByText("No seasons yet")).toBeInTheDocument();
    empty.unmount();

    let calls = 0;
    mockFetch((url) => {
      if (requestPath(url) !== "/api/v1/leagues/1/seasons/settings") {
        return errorResponse(404, { code: "not_found", message: "unexpected" });
      }
      calls += 1;
      return calls === 1
        ? errorResponse(500, { code: "boom", message: "The API is unavailable." })
        : settingsResponse([seasonSettingsResponse.seasons[1]]);
    });
    const user = userEvent.setup();
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("rowheader", { name: "2026" })).toBeInTheDocument();
  });
});
