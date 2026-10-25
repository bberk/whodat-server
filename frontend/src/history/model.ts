/**
 * View-model helpers for the History page, derived only from the Elo API response.
 *
 * A franchise is identified by `team_key` (stable across seasons); the database `team_id` is the
 * latest season's row and is used only for display. Series arrays are aligned one-to-one with the
 * API's `weeks` array, so filtering to a time window is a pure slice of both.
 */

import type { EloHistoryResponse, EloTeam, EloWeek } from "../api/types";
import type { EloChartSeries } from "../components/EloChart";

export type EloMode = "actual_schedule" | "round_robin";

export const MODE_LABELS: Readonly<Record<EloMode, string>> = {
  actual_schedule: "Actual schedule",
  round_robin: "Round robin",
};

export const MODE_DESCRIPTIONS: Readonly<Record<EloMode, string>> = {
  actual_schedule:
    "Only the stored head-to-head matchups move ratings. Cup weeks are skipped because they have no head-to-head result.",
  round_robin:
    "Every team is compared with every other team each completed week, and each team's average pairwise change is applied. Cup weeks count.",
};

export interface FilteredEloHistory {
  weeks: EloWeek[];
  teams: EloTeam[];
  boundaries: { season: number; week_index: number }[];
}

/**
 * The chart's displayed time window, chosen at week granularity.
 *
 * `all` is the default and keeps the API arrays untouched. `lastWeeks` shows the most recent N
 * chart weeks, `season` shows one stored season (which may have no rated weeks), and `range` holds
 * two week keys (`season-week`) that are resolved, clamped, and swapped before use.
 */
export type EloWindow =
  | { kind: "all" }
  | { kind: "lastWeeks"; count: number }
  | { kind: "season"; season: number }
  | { kind: "range"; startKey: string; endKey: string };

export const ALL_ELO_WINDOW: EloWindow = { kind: "all" };
export const LAST_WEEKS_PRESET = 12;

/** Stable option/state key for one chart week. */
export function eloWeekKey(week: EloWeek): string {
  return `${week.season}-${week.week}`;
}

export interface ResolvedEloWindow {
  start: number;
  end: number;
  startKey: string;
  endKey: string;
}

/**
 * Resolve a window to inclusive indices in `weeks`, with the matching select keys.
 *
 * A range with unknown keys clamps to the first/last available week; a reversed range swaps its
 * endpoints. A season with no stored chart week (or an empty chart) resolves to an empty range
 * (`end < start`), which the caller renders as the empty state rather than as an error.
 */
export function resolveEloWindow(weeks: readonly EloWeek[], window: EloWindow): ResolvedEloWindow {
  if (weeks.length === 0) {
    return { start: 0, end: -1, startKey: "", endKey: "" };
  }
  const last = weeks.length - 1;
  let start = 0;
  let end = last;
  if (window.kind === "lastWeeks") {
    if (window.count <= 0) {
      return { start: 0, end: -1, startKey: "", endKey: "" };
    }
    start = Math.max(0, weeks.length - Math.ceil(window.count));
  } else if (window.kind === "season") {
    const indices = weeks
      .map((week, index) => ({ week, index }))
      .filter((entry) => entry.week.season === window.season)
      .map((entry) => entry.index);
    if (indices.length === 0) {
      return { start: 0, end: -1, startKey: "", endKey: "" };
    }
    start = indices[0];
    end = indices[indices.length - 1];
  } else if (window.kind === "range") {
    const startIndex = weeks.findIndex((week) => eloWeekKey(week) === window.startKey);
    const endIndex = weeks.findIndex((week) => eloWeekKey(week) === window.endKey);
    start = startIndex === -1 ? 0 : startIndex;
    end = endIndex === -1 ? last : endIndex;
    if (start > end) {
      [start, end] = [end, start];
    }
  }
  return {
    start,
    end,
    startKey: eloWeekKey(weeks[start]),
    endKey: eloWeekKey(weeks[end]),
  };
}

/** Clamp and order a From/To pair so the selects can never show an inverted range. */
export function normalizeEloRange(
  weeks: readonly EloWeek[],
  startKey: string,
  endKey: string,
): { startKey: string; endKey: string } {
  const resolved = resolveEloWindow(weeks, { kind: "range", startKey, endKey });
  return { startKey: resolved.startKey, endKey: resolved.endKey };
}

/** The latest stored season, falling back to the last rated week when the season list is absent. */
export function latestEloSeason(history: EloHistoryResponse): number | null {
  if (history.seasons.length > 0) {
    return Math.max(...history.seasons);
  }
  const last = history.weeks[history.weeks.length - 1];
  return last === undefined ? null : last.season;
}

/** The "Current season" preset. */
export function currentSeasonWindow(history: EloHistoryResponse): EloWindow {
  const season = latestEloSeason(history);
  return season === null ? ALL_ELO_WINDOW : { kind: "season", season };
}

/** The "Last N weeks" preset. */
export function lastWeeksWindow(count = LAST_WEEKS_PRESET): EloWindow {
  return { kind: "lastWeeks", count };
}

/**
 * Slice the shared week/team arrays to the resolved window.
 *
 * Boundaries inside the window are shifted into the filtered x-axis so a season label still
 * aligns with its first point; a boundary at index 0 is redundant and dropped. Team series are
 * sliced in lockstep with the weeks, and out-of-window slots stay `null`.
 */
export function filterEloHistoryWindow(
  history: EloHistoryResponse,
  window: EloWindow,
): FilteredEloHistory {
  const { start, end } = resolveEloWindow(history.weeks, window);
  if (end < start) {
    return {
      weeks: [],
      teams: history.teams.map((team) => ({ ...team, series: [] })),
      boundaries: [],
    };
  }
  return {
    weeks: history.weeks.slice(start, end + 1),
    teams: history.teams.map((team) => ({
      ...team,
      series: history.weeks
        .slice(start, end + 1)
        .map((_, offset) => team.series[start + offset] ?? null),
    })),
    boundaries: history.season_boundaries
      .filter((boundary) => boundary.week_index >= start && boundary.week_index <= end)
      .map((boundary) => ({
        season: boundary.season,
        week_index: boundary.week_index - start,
      }))
      .filter((boundary) => boundary.week_index > 0),
  };
}

/** Return the chart series in stable API order, with a style index per franchise. */
export function buildEloSeries(history: EloHistoryResponse): EloChartSeries[] {
  return history.teams.map((team, index) => ({
    teamKey: team.team_key,
    name: team.name,
    ownerName: team.owner_name,
    styleIndex: index,
    values: team.series,
    current: team.current,
  }));
}

/** Current scores ordered highest first, then by name for a stable tie display. */
export function sortedEloTeams(teams: readonly EloTeam[]): EloTeam[] {
  return teams.slice().sort((left, right) => {
    const difference = Number(right.current) - Number(left.current);
    return difference === 0 ? left.name.localeCompare(right.name) : difference;
  });
}

/** Display name for a team, disambiguating duplicate current names with the owner (or season). */
export function teamDisplayName(team: EloTeam, teams: readonly EloTeam[]): string {
  const duplicated = teams.filter((other) => other.name === team.name).length > 1;
  if (!duplicated) {
    return team.name;
  }
  if (team.owner_name !== null) {
    return `${team.name} (${team.owner_name})`;
  }
  return `${team.name} (${team.last_season})`;
}
