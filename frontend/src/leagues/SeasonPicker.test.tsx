import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import { SeasonPicker } from "./SeasonPicker";

function value(overrides: Partial<LeagueContextValue> = {}): LeagueContextValue {
  return {
    leagues: [],
    leaguesStatus: "ready",
    leaguesError: null,
    selectedLeague: null,
    selectLeague: vi.fn(),
    seasons: [2025, 2026],
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

describe("SeasonPicker", () => {
  it("reports the selected season", async () => {
    const selectSeason = vi.fn();
    const user = userEvent.setup();
    const { unmount } = render(
      <LeagueContext.Provider value={value({ selectSeason })}>
        <SeasonPicker />
      </LeagueContext.Provider>,
    );
    expect(screen.getByLabelText("Season")).toHaveValue("2026");
    await user.selectOptions(screen.getByLabelText("Season"), "2025");
    expect(selectSeason).toHaveBeenCalledWith(2025);
    unmount();

    render(
      <LeagueContext.Provider
        value={value({ seasonsStatus: "loading", seasons: [], season: null })}
      >
        <SeasonPicker />
      </LeagueContext.Provider>,
    );
    expect(screen.getByText("Loading seasons…")).toBeInTheDocument();
  });
});
