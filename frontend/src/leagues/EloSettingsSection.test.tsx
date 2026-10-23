import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import {
  eloConfigResponse,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";
import { EloSettingsSection } from "./EloSettingsSection";

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
      <EloSettingsSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EloSettingsSection", () => {
  it("loads the saved settings and labels every field with a keyboard tooltip", async () => {
    mockFetch((url) =>
      requestPath(url) === "/api/v1/leagues/1/elo-config"
        ? jsonResponse(eloConfigResponse)
        : errorResponse(404, { code: "not_found", message: requestPath(url) }),
    );
    renderSection();

    expect(screen.getByRole("heading", { level: 2, name: "Elo settings" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Starting rating")).toHaveValue("1500");
    expect(screen.getByLabelText("K factor")).toHaveValue("24");
    expect(screen.getByLabelText("Margin weight")).toHaveValue("0.25");
    expect(screen.getByLabelText("Margin cap")).toHaveValue("50");
    expect(screen.getByLabelText("Season regression")).toHaveValue("0.333333");

    const trigger = screen.getByRole("button", { name: "About the K factor" });
    const tooltip = document.getElementById("elo-tip-k_factor");
    expect(trigger).toHaveAttribute("aria-describedby", "elo-tip-k_factor");
    expect(document.getElementById("elo-tip-k_factor")).toHaveAttribute("role", "tooltip");
    expect(document.getElementById("elo-tip-k_factor")?.className).toContain(
      "group-focus-within:block",
    );
    expect(tooltip).not.toBeNull();
  });

  it("saves the values, reports success, and invalidates the history view", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let putBody: Record<string, unknown> | null = null;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/elo-config" && init.method === "PUT") {
        putBody = requestBody(init);
        return jsonResponse({
          ...eloConfigResponse,
          starting_rating: "1600",
          k_factor: "32",
          margin_weight: "0.5",
          margin_cap: "40",
          season_regression: "0.5",
        });
      }
      return path === "/api/v1/leagues/1/elo-config"
        ? jsonResponse(eloConfigResponse)
        : errorResponse(404, { code: "not_found", message: path });
    });
    renderSection(value);

    await screen.findByLabelText("K factor");
    await user.clear(screen.getByLabelText("Starting rating"));
    await user.type(screen.getByLabelText("Starting rating"), "1600");
    await user.clear(screen.getByLabelText("K factor"));
    await user.type(screen.getByLabelText("K factor"), "32");
    await user.clear(screen.getByLabelText("Margin weight"));
    await user.type(screen.getByLabelText("Margin weight"), "0.5");
    await user.clear(screen.getByLabelText("Margin cap"));
    await user.type(screen.getByLabelText("Margin cap"), "40");
    await user.clear(screen.getByLabelText("Season regression"));
    await user.type(screen.getByLabelText("Season regression"), "0.5");
    await user.click(screen.getByRole("button", { name: "Recalculate Elo history" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Elo settings saved");
    expect(putBody).toEqual({
      starting_rating: "1600",
      k_factor: "32",
      margin_weight: "0.5",
      margin_cap: "40",
      season_regression: "0.5",
    });
    expect(value.notifyDataChanged).toHaveBeenCalledTimes(1);
  });

  it("restores the saved values when changes are discarded", async () => {
    const user = userEvent.setup();
    mockFetch((url) =>
      requestPath(url) === "/api/v1/leagues/1/elo-config"
        ? jsonResponse(eloConfigResponse)
        : errorResponse(404, { code: "not_found", message: requestPath(url) }),
    );
    renderSection();

    const kFactor = await screen.findByLabelText("K factor");
    await user.clear(kFactor);
    await user.type(kFactor, "32");
    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(kFactor).toHaveValue("24");
  });

  it("validates ranges before sending a request", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/elo-config" && init.method === "PUT") {
        return jsonResponse(eloConfigResponse);
      }
      return jsonResponse(eloConfigResponse);
    });
    renderSection();

    await screen.findByLabelText("Starting rating");
    await user.clear(screen.getByLabelText("Starting rating"));
    await user.type(screen.getByLabelText("Starting rating"), "999");
    await user.click(screen.getByRole("button", { name: "Recalculate Elo history" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Starting rating: Enter a number from 1000 to 2000.",
    );
    const puts = fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(puts).toHaveLength(0);
  });

  it("requires a value in every field before sending", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url) =>
      requestPath(url) === "/api/v1/leagues/1/elo-config"
        ? jsonResponse(eloConfigResponse)
        : errorResponse(404, { code: "not_found", message: requestPath(url) }),
    );
    renderSection();

    await screen.findByLabelText("K factor");
    await user.clear(screen.getByLabelText("K factor"));
    await user.click(screen.getByRole("button", { name: "Recalculate Elo history" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("K factor: Enter a value.");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(0);
  });

  it("shows loading, a recoverable load error, and a save error", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderSection();
    expect(screen.getByRole("status")).toHaveTextContent("Loading Elo settings");
    loading.unmount();

    let gets = 0;
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path !== "/api/v1/leagues/1/elo-config") {
        return errorResponse(404, { code: "not_found", message: path });
      }
      if (init.method === "PUT") {
        return errorResponse(500, { code: "boom", message: "Could not save settings." });
      }
      gets += 1;
      return gets === 1
        ? errorResponse(500, { code: "boom", message: "Could not load settings." })
        : jsonResponse(eloConfigResponse);
    });
    const user = userEvent.setup();
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load settings.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByLabelText("K factor");

    await user.click(screen.getByRole("button", { name: "Recalculate Elo history" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings.");
  });
});
