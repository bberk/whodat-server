import { describe, expect, it } from "vitest";

import {
  buildHistorySeries,
  createStandingsSource,
  defaultStandingsSource,
  emptyStandingsBundle,
  mockStandingsBundle,
  seasonHasHeadToHeadTies,
  seriesIndexByTeamId,
  weeklyBreakdownFor,
} from "./standings";

const tidy = (value: number) => Math.round(value * 100) / 100;

describe("seasonHasHeadToHeadTies", () => {
  it("is false when no team tied a matchup", () => {
    expect(seasonHasHeadToHeadTies(mockStandingsBundle.standings.overall)).toBe(false);
  });

  it("is true as soon as one team has a tie", () => {
    const tied = [
      mockStandingsBundle.standings.overall[0],
      { ...mockStandingsBundle.standings.overall[1], ties: 1 },
    ];
    expect(seasonHasHeadToHeadTies(tied)).toBe(true);
  });
});

describe("standings bundle consistency", () => {
  it("keeps the standings weekly VP equal to the history weekly VP", () => {
    const historyByTeam = new Map(
      mockStandingsBundle.history.teams.map((team) => [team.team_id, team.weekly]),
    );
    for (const row of mockStandingsBundle.standings.overall) {
      expect(row.weekly_vp).toEqual(historyByTeam.get(row.team_id));
    }
  });

  it("has a cumulative series equal to the running sum of the weekly VP", () => {
    for (const team of mockStandingsBundle.history.teams) {
      let running = 0;
      const expected = team.weekly.map((weekly) => {
        running = tidy(running + Number(weekly));
        return running;
      });
      expect(team.cumulative.map(Number)).toEqual(expected);
    }
  });

  it("ends each team's cumulative series at its season VP", () => {
    const seasonByTeam = new Map(
      mockStandingsBundle.standings.overall.map((row) => [row.team_id, row.victory_points]),
    );
    for (const team of mockStandingsBundle.history.teams) {
      expect(tidy(Number(team.cumulative[team.cumulative.length - 1]))).toBe(
        tidy(Number(seasonByTeam.get(team.team_id))),
      );
    }
  });

  it("carries overall league ranks in the division rows, not division-local ones", () => {
    const rankByTeam = new Map(
      mockStandingsBundle.standings.overall.map((row) => [row.team_id, row.rank]),
    );
    for (const division of mockStandingsBundle.standings.divisions) {
      const ranks = division.standings.map((row) => row.rank);
      expect(ranks).toEqual(division.standings.map((row) => rankByTeam.get(row.team_id)));
      expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    }
    const west = mockStandingsBundle.standings.divisions.find((row) => row.name === "West");
    expect(west?.standings.map((row) => row.rank)).toEqual([4, 5, 6]);
  });

  it("has weekly component rows that add up to the displayed total", () => {
    for (const week of mockStandingsBundle.weekly) {
      for (const row of week.rows) {
        const sum = tidy(
          Number(row.h2h) + Number(row.top_half) + Number(row.high) + Number(row.low),
        );
        expect(sum).toBe(tidy(Number(row.total)));
      }
    }
  });
});

describe("buildHistorySeries", () => {
  it("assigns a stable style index in history order", () => {
    const series = buildHistorySeries(mockStandingsBundle);
    expect(series.map((entry) => entry.teamId)).toEqual([7, 3, 9, 2, 5, 4]);
    expect(series.map((entry) => entry.styleIndex)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("exposes the same style index through the lookup map", () => {
    const styles = seriesIndexByTeamId(mockStandingsBundle);
    expect(styles.get(7)).toBe(0);
    expect(styles.get(4)).toBe(5);
  });
});

describe("weeklyBreakdownFor", () => {
  it("orders a week's rows by that week's total VP then overall rank", () => {
    const { rows, note } = weeklyBreakdownFor(mockStandingsBundle, 4);
    expect(rows.map((row) => row.teamName)).toEqual([
      "Alpha",
      "Bravo",
      "Echo",
      "Charlie",
      "Delta",
      "Foxtrot",
    ]);
    expect(note).toContain("example D");
  });

  it("returns nothing for a week with no components", () => {
    expect(weeklyBreakdownFor(mockStandingsBundle, 9)).toEqual({ rows: [], note: null });
  });
});

describe("createStandingsSource", () => {
  it("resolves ready data by default", async () => {
    await expect(createStandingsSource().load()).resolves.toBe(mockStandingsBundle);
  });

  it("resolves the empty bundle for the empty scenario", async () => {
    await expect(createStandingsSource("empty").load()).resolves.toBe(emptyStandingsBundle);
  });

  it("rejects for the error scenario", async () => {
    await expect(createStandingsSource("error").load()).rejects.toThrow(
      "The standings request failed",
    );
  });

  it("never settles for the loading scenario", async () => {
    let settled = false;
    void createStandingsSource("loading")
      .load()
      .then(() => {
        settled = true;
      });
    await Promise.resolve();
    expect(settled).toBe(false);
  });

  it("exposes a default ready source for the page", async () => {
    await expect(defaultStandingsSource.load()).resolves.toBe(mockStandingsBundle);
  });
});
