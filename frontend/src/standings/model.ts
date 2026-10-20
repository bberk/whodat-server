/**
 * View-model helpers for standings, derived only from fields the API returns.
 *
 * The API exposes overall/division rows, weekly VP totals, and cumulative VP. It does not expose
 * the per-component split (H2H, top half, high score, low score), so the weekly view shows the
 * weekly and cumulative totals that are actually present rather than inventing components.
 */

import type { StandingsRow, VpHistoryResponse } from "../api/types";
import type { ChartSeries } from "../components/VPChart";
import { toNumber } from "../components/format";

/** True when any team recorded an H2H tie, which switches the record column to W-L-T. */
export function seasonHasHeadToHeadTies(rows: readonly StandingsRow[]): boolean {
  return rows.some((row) => row.ties > 0);
}

/**
 * The chart series in history order. `styleIndex` drives the color/dash/marker pairing so a team
 * keeps the same visual identity in the table tag, the legend, and the chart.
 */
export function buildHistorySeries(history: VpHistoryResponse): ChartSeries[] {
  return history.teams.map((team, index) => ({
    teamId: team.team_id,
    teamName: team.team_name,
    styleIndex: index,
    cumulative: team.cumulative,
  }));
}

export function seriesIndexByTeamId(history: VpHistoryResponse): Map<number, number> {
  return new Map(history.teams.map((team, index) => [team.team_id, index]));
}

export interface WeeklyBreakdownRow {
  teamId: number;
  teamName: string;
  styleIndex: number;
  weekly: string;
  cumulative: string;
  overallRank: number;
}

export interface WeeklyBreakdown {
  rows: WeeklyBreakdownRow[];
  note: string | null;
}

/** Weekly and cumulative VP for one week, ordered by that week's VP then overall rank. */
export function weeklyBreakdownFor(
  history: VpHistoryResponse,
  overall: readonly StandingsRow[],
  week: number,
): WeeklyBreakdown {
  const index = history.weeks.indexOf(week);
  if (index === -1) {
    return { rows: [], note: null };
  }
  const rankByTeam = new Map(overall.map((row) => [row.team_id, row.rank]));
  const rows = history.teams.map((team, styleIndex) => ({
    teamId: team.team_id,
    teamName: team.team_name,
    styleIndex,
    weekly: team.weekly[index] ?? "0",
    cumulative: team.cumulative[index] ?? "0",
    overallRank: rankByTeam.get(team.team_id) ?? 0,
  }));
  rows.sort((a, b) => toNumber(b.weekly) - toNumber(a.weekly) || a.overallRank - b.overallRank);
  return { rows, note: null };
}
