import { describe, expect, it } from "vitest";

import { eloHistoryResponse } from "../test/fixtures";
import {
  buildEloSeries,
  filterEloHistory,
  seasonFilterLabel,
  sortedEloTeams,
  teamDisplayName,
} from "./model";

describe("buildEloSeries", () => {
  it("keeps API order and assigns a stable style index", () => {
    const series = buildEloSeries(eloHistoryResponse);

    expect(series.map((entry) => entry.teamKey)).toEqual(["espn:1", "espn:2", "espn:3"]);
    expect(series.map((entry) => entry.styleIndex)).toEqual([0, 1, 2]);
  });
});

describe("filterEloHistory", () => {
  it("returns all history unchanged for the All history filter", () => {
    const filtered = filterEloHistory(eloHistoryResponse, null);

    expect(filtered.weeks).toBe(eloHistoryResponse.weeks);
    expect(filtered.teams).toBe(eloHistoryResponse.teams);
    expect(filtered.boundaries).toBe(eloHistoryResponse.season_boundaries);
  });

  it("slices weeks, series, and boundaries to one season", () => {
    const withBoundary = {
      ...eloHistoryResponse,
      season_boundaries: [{ season: 2025, week_index: 2 }],
    };
    const filtered = filterEloHistory(withBoundary, 2025);

    expect(filtered.weeks.map((week) => week.week)).toEqual([1, 2]);
    expect(filtered.teams[0].series).toEqual(["1512.6", "1512.6"]);
    expect(filtered.boundaries).toEqual([{ season: 2025, week_index: 2 }]);
  });

  it("returns no weeks when a season has no stored chart slot", () => {
    const filtered = filterEloHistory({ ...eloHistoryResponse, seasons: [2024, 2025] }, 2024);

    expect(filtered.weeks).toEqual([]);
    expect(filtered.boundaries).toEqual([]);
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

describe("seasonFilterLabel", () => {
  it("labels the all-history choice and a specific season", () => {
    expect(seasonFilterLabel(null)).toBe("All history");
    expect(seasonFilterLabel(2026)).toBe("2026");
  });
});
