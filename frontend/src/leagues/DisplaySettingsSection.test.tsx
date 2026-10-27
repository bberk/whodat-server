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
import { DisplaySettingsSection } from "./DisplaySettingsSection";
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
      <DisplaySettingsSection leagueId={1} />
    </LeagueContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DisplaySettingsSection", () => {
  it("shows the WAPDate flag as on by default without a GET request", () => {
    const fetchMock = mockFetch(() =>
      errorResponse(404, { code: "not_found", message: "unexpected request" }),
    );
    renderSection();

    expect(screen.getByRole("heading", { level: 2, name: "Display settings" })).toBeInTheDocument();
    const toggle = screen.getByRole("checkbox", { name: "WAPDate standings" });
    expect(toggle).toBeChecked();
    expect(toggle).toHaveAccessibleDescription(
      /Some leagues do not use this quirk; turning it off hides the section/i,
    );
    expect(screen.getByText("The standings page shows this section.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("saves the flag, replaces the cached league, and reports success", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    let putBody: Record<string, unknown> | null = null;
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/display-settings" && init.method === "PUT") {
        putBody = requestBody(init);
        return jsonResponse({ ...leagueAlpha, show_wapdate: false });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });
    renderSection(value);

    await user.click(screen.getByRole("checkbox", { name: "WAPDate standings" }));
    expect(screen.getByRole("checkbox", { name: "WAPDate standings" })).not.toBeChecked();
    expect(screen.getByText("The standings page hides this section.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save display settings" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "WAPDate standings section hidden from the standings page.",
    );
    expect(putBody).toEqual({ show_wapdate: false });
    expect(value.upsertLeague).toHaveBeenCalledWith({ ...leagueAlpha, show_wapdate: false });
  });

  it("keeps the chosen value and shows the error when saving fails", async () => {
    const user = userEvent.setup();
    const value = leagueValue();
    mockFetch(() => errorResponse(500, { code: "boom", message: "Could not save settings." }));
    renderSection(value);

    await user.click(screen.getByRole("checkbox", { name: "WAPDate standings" }));
    await user.click(screen.getByRole("button", { name: "Save display settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings.");
    expect(screen.getByRole("checkbox", { name: "WAPDate standings" })).not.toBeChecked();
    expect(value.upsertLeague).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a loading state while the league list loads", () => {
    mockFetch(() => errorResponse(404, { code: "not_found", message: "unexpected request" }));
    renderSection(leagueValue({ leaguesStatus: "loading", selectedLeague: null, leagues: [] }));

    expect(screen.getByRole("status")).toHaveTextContent("Loading display settings");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("offers a retry when the league list failed and explains a missing league", async () => {
    const user = userEvent.setup();
    const value = leagueValue({
      leaguesStatus: "error",
      leaguesError: "Could not load your leagues.",
      leagues: [],
      selectedLeague: null,
    });
    mockFetch(() => errorResponse(500, { code: "boom", message: "Could not load leagues." }));
    const view = renderSection(value);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your leagues.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(value.reloadLeagues).toHaveBeenCalledTimes(1);
    view.unmount();

    renderSection(leagueValue({ leagues: [], selectedLeague: null }));
    expect(screen.getByText("League not found")).toBeInTheDocument();
  });

  it("keeps no stale draft when the route switches league", async () => {
    const user = userEvent.setup();
    mockFetch(() => errorResponse(404, { code: "not_found", message: "unexpected request" }));
    const view = render(
      <LeagueContext.Provider value={leagueValue()}>
        <DisplaySettingsSection leagueId={1} />
      </LeagueContext.Provider>,
    );

    await user.click(screen.getByRole("checkbox", { name: "WAPDate standings" }));
    expect(screen.getByRole("checkbox", { name: "WAPDate standings" })).not.toBeChecked();
    view.rerender(
      <LeagueContext.Provider value={leagueValue()}>
        <DisplaySettingsSection leagueId={2} />
      </LeagueContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByText("League not found")).toBeInTheDocument();
    });
    view.unmount();

    renderSection();
    expect(screen.getByRole("checkbox", { name: "WAPDate standings" })).toBeChecked();
  });
});
