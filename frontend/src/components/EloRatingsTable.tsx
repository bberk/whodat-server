import { useState } from "react";

import type { EloTeam } from "../api/types";
import { formatEloChange, formatEloValue, formatEloWhole } from "./format";
import { sortedEloTeams, teamDisplayName } from "../history/model";
import { SortableHeader } from "./SortableHeader";
import {
  sortRows,
  toggleSort,
  type SortDirection,
  type SortState,
  type SortValue,
} from "./sorting";

export interface EloRatingsTableProps {
  teams: readonly EloTeam[];
  selectedTeamKey: string | null;
  onSelectTeam: (teamKey: string) => void;
}

const headCell =
  "whitespace-nowrap border-b border-gray-200 bg-gray-50 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";
const RANK_CELL = "sticky left-0 z-10 w-11 min-w-11 max-w-11";
const RANK_HEAD = "sticky left-0 z-20 w-11 min-w-11 max-w-11";
const TEAM_CELL = "sticky left-11 z-10 min-w-[168px]";
const TEAM_HEAD = "sticky left-11 z-20 min-w-[168px]";
const PINNED_SHADOW = "shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]";
const ROW_DIVIDER =
  "[&>th]:border-b [&>td]:border-b [&>th]:border-gray-100 [&>td]:border-gray-100 last:[&>th]:border-b-0 last:[&>td]:border-b-0";

/** Format a peak/low reference as a short "season Wweek" label, or "start". */
function referenceLabel(reference: { season: number; week: number } | null): string {
  return reference === null ? "start" : `${reference.season} W${reference.week}`;
}

/** Numeric value for a sortable Elo column. */
function sortValueFor(team: EloTeam, key: string): SortValue {
  switch (key) {
    case "elo":
      return Number(team.current);
    case "last":
      return Number(team.last_change);
    case "season":
      return Number(team.season_change);
    case "peak":
      return Number(team.peak);
    case "low":
      return Number(team.low);
    default:
      return null;
  }
}

/**
 * Current Elo scores, highest first.
 *
 * The Elo score is rounded to a whole number; week and season changes keep two decimals and an
 * explicit sign. Peak and low name the week they happened (or "start"). Wide content scrolls
 * inside the region with the rank and team columns pinned, so the page body never scrolls
 * sideways at 360px. Selecting a row highlights that franchise in the chart.
 *
 * Elo, last week, this season, peak, and low sort on the client. The rank column stays the
 * current-score rank supplied by the data layer, so sorting never re-ranks a team; team and owner
 * are not sortable.
 */
export function EloRatingsTable({ teams, selectedTeamKey, onSelectTeam }: EloRatingsTableProps) {
  const [sort, setSort] = useState<SortState | null>(null);
  const currentOrder = sortedEloTeams(teams);
  const rankByKey = new Map(currentOrder.map((team, index) => [team.team_key, index + 1]));
  const ordered = sort === null ? currentOrder : sortRows(currentOrder, sort, sortValueFor);

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  return (
    <div
      className="relative mt-3 overflow-x-auto rounded-xl border border-gray-200 bg-white"
      tabIndex={0}
      role="region"
      aria-label="Elo score history current scores, scrollable horizontally"
    >
      <table className="w-full min-w-[760px] border-separate border-spacing-0 text-left text-[13px]">
        <caption className="sr-only">
          Current Elo scores sorted by current score, with change over the last week, change this
          season, peak, low, and owner. Elo, last week, this season, peak, and low are sortable; the
          rank shown is always the current-score rank.
        </caption>
        <thead>
          <tr>
            <th scope="col" className={`${headCell} ${RANK_HEAD} text-right`}>
              #
            </th>
            <th scope="col" className={`${headCell} ${TEAM_HEAD} ${PINNED_SHADOW}`}>
              Team
            </th>
            <SortableHeader
              label="Elo score"
              sortKey="elo"
              state={sort}
              onSort={handleSort}
              initialDirection="desc"
              className={headCell}
            />
            <SortableHeader
              label="Last week"
              sortKey="last"
              state={sort}
              onSort={handleSort}
              initialDirection="desc"
              className={headCell}
            />
            <SortableHeader
              label="This season"
              sortKey="season"
              state={sort}
              onSort={handleSort}
              initialDirection="desc"
              className={headCell}
            />
            <SortableHeader
              label="Peak"
              sortKey="peak"
              state={sort}
              onSort={handleSort}
              initialDirection="desc"
              className={headCell}
            />
            <SortableHeader
              label="Low"
              sortKey="low"
              state={sort}
              onSort={handleSort}
              initialDirection="desc"
              className={headCell}
            />
            <th scope="col" className={headCell}>
              Owner
            </th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((team) => {
            const selected = team.team_key === selectedTeamKey;
            const name = teamDisplayName(team, teams);
            const pinnedBackground = selected
              ? "bg-brand-foreground"
              : "bg-white group-hover:bg-gray-50";
            return (
              <tr
                key={team.team_key}
                className={`group ${ROW_DIVIDER} ${selected ? "bg-brand-foreground" : "hover:bg-gray-50"}`}
              >
                <th
                  scope="row"
                  className={`${RANK_CELL} ${pinnedBackground} px-3 py-2 text-right font-semibold tabular-nums text-gray-500`}
                >
                  {rankByKey.get(team.team_key)}
                </th>
                <td className={`${TEAM_CELL} ${PINNED_SHADOW} px-3 py-2 ${pinnedBackground}`}>
                  <button
                    type="button"
                    onClick={() => onSelectTeam(team.team_key)}
                    aria-pressed={selected}
                    className={`text-left font-semibold hover:text-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                      selected ? "text-brand" : "text-gray-900"
                    }`}
                  >
                    {name}
                  </button>
                  {selected ? <span className="ml-1 text-[11px] text-brand">selected</span> : null}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right text-[15px] font-bold tabular-nums">
                  {formatEloWhole(team.current)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatEloChange(team.last_change)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatEloChange(team.season_change)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatEloValue(team.peak)}
                  <span className="ml-1 text-[11px] text-gray-500">
                    {referenceLabel(team.peak_at)}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-700">
                  {formatEloValue(team.low)}
                  <span className="ml-1 text-[11px] text-gray-500">
                    {referenceLabel(team.low_at)}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                  {team.owner_name ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
