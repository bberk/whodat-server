import { describe, expect, it } from "vitest";

import type { EloWeek } from "../api/types";
import { eloHistoryResponse } from "../test/fixtures";
import {
  ALL_ELO_WINDOW,
  LAST_WEEKS_PRESET,
  buildEloSeries,
  currentSeasonWindow,
  eloWeekKey,
  filterEloHistoryWindow,
  lastWeeksWindow,
  latestEloSeason,
  normalizeEloRange,
  resolveEloWindow,
  sortedEloTeams,
  teamDisplayName,
} from "./model";

const weeks = eloHistoryResponse.weeks;

describe("buildEloSeries", () => {
  it("keeps API order and assigns a stable style index", () => {
    const series = buildEloSeries(eloHistoryResponse);

    expect(series.map((entry) => entry.teamKey)).toEqual(["espn:1", "espn:2", "espn:3"]);
    expect(series.map((entry) => entry.styleIndex)).toEqual([0, 1, 2]);
  });
});

describe("resolveEloWindow", () => {
  it("resolves the all-history window to every week", () => {
    expect(resolveEloWindow(weeks, ALL_ELO_WINDOW)).toEqual({
      start: 0,
      end: 2,
      startKey: "2025-1",
      endKey: "2026-1",
    });
  });

  it("resolves the last N weeks and clamps a count larger than the range", () => {
    expect(resolveEloWindow(weeks, lastWeeksWindow(2))).toEqual({
      start: 1,
      end: 2,
      startKey: "2025-2",
      endKey: "2026-1",
    });
    expect(resolveEloWindow(weeks, lastWeeksWindow(99))).toEqual({
      start: 0,
      end: 2,
      startKey: "2025-1",
      endKey: "2026-1",
    });
  });

  it("returns an empty range for a non-positive last-weeks count", () => {
    expect(resolveEloWindow(weeks, lastWeeksWindow(0))).toEqual({
      start: 0,
      end: -1,
      startKey: "",
      endKey: "",
    });
  });

  it("resolves a season, and reports an empty range for a season with no weeks", () => {
    expect(resolveEloWindow(weeks, { kind: "season", season: 2025 })).toEqual({
      start: 0,
      end: 1,
      startKey: "2025-1",
      endKey: "2025-2",
    });
    expect(resolveEloWindow(weeks, { kind: "season", season: 2024 })).toEqual({
      start: 0,
      end: -1,
      startKey: "",
      endKey: "",
    });
  });

  it("swaps a reversed range and clamps unknown keys to the available ends", () => {
    expect(
      resolveEloWindow(weeks, { kind: "range", startKey: "2026-1", endKey: "2025-1" }),
    ).toEqual({ start: 0, end: 2, startKey: "2025-1", endKey: "2026-1" });
    expect(
      resolveEloWindow(weeks, { kind: "range", startKey: "1999-1", endKey: "2030-1" }),
    ).toEqual({ start: 0, end: 2, startKey: "2025-1", endKey: "2026-1" });
  });

  it("handles an empty chart", () => {
    const empty: EloWeek[] = [];
    expect(resolveEloWindow(empty, ALL_ELO_WINDOW)).toEqual({
      start: 0,
      end: -1,
      startKey: "",
      endKey: "",
    });
  });
});

describe("normalizeEloRange", () => {
  it("returns ordered keys for an inverted pair", () => {
    expect(normalizeEloRange(weeks, "2026-1", "2025-2")).toEqual({
      startKey: "2025-2",
      endKey: "2026-1",
    });
  });
});

describe("filterEloHistoryWindow", () => {
  it("keeps every array for the all-history window", () => {
    const filtered = filterEloHistoryWindow(eloHistoryResponse, ALL_ELO_WINDOW);

    expect(filtered.weeks).toEqual(eloHistoryResponse.weeks);
    expect(filtered.teams.map((team) => team.series)).toEqual(
      eloHistoryResponse.teams.map((team) => team.series),
    );
    expect(filtered.boundaries).toEqual(eloHistoryResponse.season_boundaries);
  });

  it("slices weeks, series, and boundaries to one season", () => {
    const withBoundary = {
      ...eloHistoryResponse,
      season_boundaries: [{ season: 2025, week_index: 1 }],
    };
    const filtered = filterEloHistoryWindow(withBoundary, { kind: "season", season: 2025 });

    expect(filtered.weeks.map((week) => week.week)).toEqual([1, 2]);
    expect(filtered.teams[0].series).toEqual(["1512.6", "1512.6"]);
    expect(filtered.boundaries).toEqual([{ season: 2025, week_index: 1 }]);
  });

  it("keeps null slots for a team that was not in the window's seasons", () => {
    const filtered = filterEloHistoryWindow(eloHistoryResponse, {
      kind: "season",
      season: 2025,
    });
    const charlie = filtered.teams.find((team) => team.team_key === "espn:3");
    expect(charlie?.series).toEqual([null, null]);
  });

  it("slices a custom range and shifts its boundaries", () => {
    const filtered = filterEloHistoryWindow(eloHistoryResponse, {
      kind: "range",
      startKey: "2025-2",
      endKey: "2026-1",
    });

    expect(filtered.weeks.map(eloWeekKey)).toEqual(["2025-2", "2026-1"]);
    expect(filtered.teams[0].series).toEqual(["1512.6", "1525.2"]);
    expect(filtered.boundaries).toEqual([{ season: 2026, week_index: 1 }]);
  });

  it("drops a boundary that would sit at index zero", () => {
    const filtered = filterEloHistoryWindow(
      {
        ...eloHistoryResponse,
        season_boundaries: [{ season: 2026, week_index: 2 }],
      },
      { kind: "range", startKey: "2026-1", endKey: "2026-1" },
    );
    expect(filtered.weeks.map(eloWeekKey)).toEqual(["2026-1"]);
    expect(filtered.boundaries).toEqual([]);
  });

  it("returns an empty view for a season with no rated weeks", () => {
    const filtered = filterEloHistoryWindow(
      { ...eloHistoryResponse, seasons: [2024, 2025] },
      { kind: "season", season: 2024 },
    );

    expect(filtered.weeks).toEqual([]);
    expect(filtered.teams[0].series).toEqual([]);
    expect(filtered.boundaries).toEqual([]);
  });
});

describe("season presets", () => {
  it("uses the latest stored season for the current-season preset", () => {
    expect(latestEloSeason(eloHistoryResponse)).toBe(2026);
    expect(currentSeasonWindow(eloHistoryResponse)).toEqual({ kind: "season", season: 2026 });
  });

  it("falls back to the last rated week when the season list is absent", () => {
    expect(latestEloSeason({ ...eloHistoryResponse, seasons: [] })).toBe(2026);
  });

  it("has no current season when the response has neither seasons nor weeks", () => {
    const empty = { ...eloHistoryResponse, seasons: [], weeks: [] };
    expect(latestEloSeason(empty)).toBeNull();
    expect(currentSeasonWindow(empty)).toEqual(ALL_ELO_WINDOW);
  });

  it("exposes the twelve-week preset", () => {
    expect(LAST_WEEKS_PRESET).toBe(12);
    expect(lastWeeksWindow()).toEqual({ kind: "lastWeeks", count: 12 });
  });
});

describe("sortedEloTeams", () => {
  it("sorts by current rating and then by name for a tie", () => {
    const teams = eloHistoryResponse.teams.map((team, index) =>
      index === 1 ? { ...team, current: "1525.2" } : team,
    );
    const sorted = sortedEloTeams(teams);

    expect(sorted.map((team) => team.name)).toEqual(["Alpha", "Bravo", "Charlie"]);
  });
});

describe("teamDisplayName", () => {
  it("uses the plain name when it is unique", () => {
    expect(teamDisplayName(eloHistoryResponse.teams[0], eloHistoryResponse.teams)).toBe("Alpha");
  });

  it("adds the owner when two current names collide", () => {
    const teams = [
      eloHistoryResponse.teams[0],
      { ...eloHistoryResponse.teams[1], name: "Alpha", owner_name: "Blair" },
    ];

    expect(teamDisplayName(teams[0], teams)).toBe("Alpha (Alex)");
    expect(teamDisplayName(teams[1], teams)).toBe("Alpha (Blair)");
  });

  it("falls back to the last season when duplicate teams have no owner", () => {
    const teams = [
      { ...eloHistoryResponse.teams[2], name: "Same", owner_name: null },
      { ...eloHistoryResponse.teams[2], name: "Same", owner_name: null, last_season: 2025 },
    ];

    expect(teamDisplayName(teams[0], teams)).toBe("Same (2026)");
  });
});
