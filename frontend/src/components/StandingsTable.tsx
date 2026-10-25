import { useState } from "react";

import type { StandingsRow } from "../api/types";
import { ClinchBadge } from "./ClinchBadge";
import { formatPoints, formatRecord, formatVP, vpTone, vpToneClass } from "./format";
import { seriesStyle } from "./series";
import { SortableHeader } from "./SortableHeader";
import {
  sortRows,
  toggleSort,
  type SortDirection,
  type SortState,
  type SortValue,
} from "./sorting";

export interface StandingsTableProps {
  /** Visually hidden description of the table (screen-reader caption). */
  caption: string;
  /** Accessible name for the horizontal scroll region. */
  ariaLabel: string;
  rows: StandingsRow[];
  /** Weekly VP columns to render; empty for division tables, which keep the overall-only detail. */
  weeks: number[];
  showTies: boolean;
  selectedTeamId: number | null;
  onSelectTeam: (teamId: number) => void;
  seriesIndexByTeamId: ReadonlyMap<number, number>;
}

/**
 * The rank column is pinned at exactly 48px and the team column starts at the same 48px. The
 * browser's table layout will grow other columns, but it may not shrink the rank column below its
 * content width, so an exact `min`/`max` pair is what keeps the two offsets equal. When they drift
 * apart, the columns behind the pinned pair show through the gap between them.
 */
const RANK_CELL = "sticky left-0 z-10 w-12 min-w-12 max-w-12";
const RANK_HEAD = "sticky left-0 z-20 w-12 min-w-12 max-w-12";
const TEAM_CELL = "sticky left-12 z-10 min-w-[176px]";
const TEAM_HEAD = "sticky left-12 z-20 min-w-[176px]";
const PINNED_SHADOW = "shadow-sticky";
const ROW_DIVIDER =
  "[&>th]:border-b [&>td]:border-b [&>th]:border-line [&>td]:border-line last:[&>th]:border-b-0 last:[&>td]:border-b-0";
const HEAD_DIVIDER = "[&>th]:border-b [&>th]:border-line-strong";

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

/** Numeric value for a sortable column; `null` keeps missing values last in either direction. */
function sortValueFor(row: StandingsRow, key: string, weeks: readonly number[]): SortValue {
  switch (key) {
    case "vp":
      return Number(row.victory_points);
    case "record":
      return row.wins;
    case "pf":
      return Number(row.points_for);
    default:
      break;
  }
  if (key.startsWith("week:")) {
    const week = Number(key.slice("week:".length));
    const index = weeks.indexOf(week);
    const value = index === -1 ? undefined : row.weekly_vp[index];
    return value === undefined || value === null ? null : Number(value);
  }
  return null;
}

/**
 * The standings table, reused for the overall table and for each division. The rank cell renders
 * `row.rank` exactly as the data layer supplies it and this component never ranks or re-ranks: for
 * a division table that value is the team's overall league rank (a division only groups/filters
 * rows). Wide content scrolls inside its own region with the rank and team columns pinned; the
 * team cell is a button so selecting a team is keyboard operable.
 *
 * Season VP, the record, points for, and each weekly VP column are sortable. Team, owner, and rank
 * are not: identity columns keep the API's rank order, and the rank value never changes when the
 * client sorts. Division tables pass no `weeks`, so they never render weekly VP columns.
 *
 * Pinned cells carry an opaque theme token (never `bg-inherit`), so scrolled content cannot show
 * through the rank and team columns in either theme.
 */
export function StandingsTable({
  caption,
  ariaLabel,
  rows,
  weeks,
  showTies,
  selectedTeamId,
  onSelectTeam,
  seriesIndexByTeamId,
}: StandingsTableProps) {
  const [sort, setSort] = useState<SortState | null>(null);

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  const orderedRows = sortRows(rows, sort, (row, key) => sortValueFor(row, key, weeks));

  return (
    <div className="relative mt-3">
      {/* `relative` keeps any absolutely positioned descendant (for example a visually hidden
          label) inside this scroll container; without it such a box escapes the clip and makes
          the whole page scroll sideways at narrow widths. */}
      <div
        className="relative overflow-x-auto rounded-xl border border-line bg-surface"
        tabIndex={0}
        role="region"
        aria-label={ariaLabel}
      >
        <table className="w-full min-w-[700px] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className={HEAD_DIVIDER}>
              <th scope="col" className={`${headCell} ${RANK_HEAD} bg-surface text-left`}>
                #
              </th>
              <th scope="col" className={`${headCell} ${TEAM_HEAD} ${PINNED_SHADOW} bg-surface`}>
                Team
              </th>
              <th scope="col" className={headCell}>
                Owner
              </th>
              <SortableHeader
                label="Season VP"
                sortKey="vp"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={headCell}
              />
              <SortableHeader
                label={showTies ? "W-L-T" : "W-L"}
                sortKey="record"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={headCell}
              />
              <SortableHeader
                label="Points for"
                sortKey="pf"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={headCell}
              />
              {weeks.map((week) => (
                <SortableHeader
                  key={week}
                  label={`W${week}`}
                  headerLabel={`Week ${week} VP`}
                  buttonLabel={`Sort by week ${week} VP`}
                  sortKey={`week:${week}`}
                  state={sort}
                  onSort={handleSort}
                  initialDirection="desc"
                  className={headCell}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {orderedRows.map((row) => {
              const selected = row.team_id === selectedTeamId;
              const stickyBackground = selected
                ? "bg-brand-soft"
                : "bg-surface group-hover:bg-surface-hover";
              const style = seriesStyle(seriesIndexByTeamId.get(row.team_id) ?? 0);
              return (
                <tr
                  key={row.team_id}
                  className={`group ${ROW_DIVIDER} ${
                    selected ? "bg-brand-soft" : "hover:bg-surface-hover"
                  }`}
                >
                  <th
                    scope="row"
                    className={`${numCell} ${RANK_CELL} text-left font-normal text-ink-subtle ${stickyBackground} ${
                      selected ? "shadow-[inset_3px_0_0_0_rgb(var(--color-brand-ink))]" : ""
                    }`}
                  >
                    {row.rank}
                  </th>
                  <td className={`${TEAM_CELL} ${PINNED_SHADOW} px-3 py-2 ${stickyBackground}`}>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        aria-pressed={selected}
                        onClick={() => onSelectTeam(row.team_id)}
                        className="flex min-w-0 flex-1 items-center gap-2 rounded text-left font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink"
                      >
                        <span
                          aria-hidden="true"
                          className="inline-flex h-5 w-5 flex-none items-center justify-center rounded-md border text-[11px] font-bold"
                          style={{ color: style.color, borderColor: style.color }}
                        >
                          {row.team_name.charAt(0)}
                        </span>
                        <span>{row.team_name}</span>
                      </button>
                      <ClinchBadge status={row.clinch} />
                    </div>
                  </td>
                  <td className={`${numCell} text-left text-ink-subtle`}>
                    {row.owner_name ?? "—"}
                  </td>
                  <td className={`${numCell} font-bold ${vpToneClass(vpTone(row.victory_points))}`}>
                    {formatVP(row.victory_points)}
                  </td>
                  <td className={`${numCell} text-ink-subtle`}>{formatRecord(row, showTies)}</td>
                  <td className={`${numCell} text-ink-subtle`}>{formatPoints(row.points_for)}</td>
                  {row.weekly_vp.map((vp, index) => {
                    if (weeks[index] === undefined) {
                      return null;
                    }
                    return (
                      <td
                        key={`week-${weeks[index]}`}
                        className={`${numCell} font-medium ${vpToneClass(vpTone(vp))}`}
                      >
                        {formatVP(vp)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 z-30 w-7 rounded-r-xl bg-gradient-to-l from-fade/5 to-transparent"
      />
    </div>
  );
}
