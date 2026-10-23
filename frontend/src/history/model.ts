/**
 * View-model helpers for the History page, derived only from the Elo API response.
 *
 * A franchise is identified by `team_key` (stable across seasons); the database `team_id` is the
 * latest season's row and is used only for display. Series arrays are aligned one-to-one with the
 * API's `weeks` array, so filtering to a season is a pure slice of both.
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

/**
 * Slice the shared week/team arrays to one season, or return all history for `null`.
 *
 * A team absent from the chosen season keeps its null series values. The boundaries are shifted
 * into the filtered x-axis so a season label still aligns with its first point.
 */
export function filterEloHistory(
  history: EloHistoryResponse,
  season: number | null,
): FilteredEloHistory {
  if (season === null) {
    return {
      weeks: history.weeks,
      teams: history.teams,
      boundaries: history.season_boundaries,
    };
  }
  const indices = history.weeks
    .map((week, index) => ({ week, index }))
    .filter((entry) => entry.week.season === season);
  const offset = indices.length === 0 ? 0 : indices[0].index;
  return {
    weeks: indices.map((entry) => entry.week),
    teams: history.teams.map((team) => ({
      ...team,
      series: indices.map((entry) => team.series[entry.index] ?? null),
    })),
    boundaries: history.season_boundaries
      .filter((boundary) => boundary.season === season)
      .map((boundary) => ({ season: boundary.season, week_index: boundary.week_index - offset }))
      .filter((boundary) => boundary.week_index > 0),
  };
}

/** Current scores ordered highest first, then by name for a stable tie display. */
export function sortedEloTeams(teams: readonly EloTeam[]): EloTeam[] {
  return teams.slice().sort((left, right) => {
    const difference = Number(right.current) - Number(left.current);
    return difference === 0 ? left.name.localeCompare(right.name) : difference;
  });
}

/**
 * Display name for a team, disambiguating duplicate current names with the owner (or season).
 * The API never keys by name; this only prevents two identical labels in the UI.
 */
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

/** Human-readable label for a season filter, including "All history". */
export function seasonFilterLabel(season: number | null): string {
  return season === null ? "All history" : String(season);
}
