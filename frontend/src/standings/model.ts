/**
 * View-model helpers for standings, derived only from fields the API returns.
 *
 * The API exposes overall/division rows, weekly VP totals, and cumulative VP; these helpers shape
 * that data for the standings tables and the cumulative VP chart.
 */

import type { StandingsRow, VpHistoryResponse } from "../api/types";
import type { ChartSeries } from "../components/VPChart";

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
