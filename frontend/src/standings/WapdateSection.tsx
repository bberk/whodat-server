import { useState } from "react";

import type { WapdatePeriod, WapdateRow } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { formatPoints, formatVP } from "../components/format";
import { SortableHeader } from "../components/SortableHeader";
import {
  sortRows,
  toggleSort,
  type SortDirection,
  type SortState,
  type SortValue,
} from "../components/sorting";
import { useWapdateData } from "./useWapdateData";

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";
const ROW_DIVIDER =
  "[&>th]:border-b [&>td]:border-b [&>th]:border-line [&>td]:border-line last:[&>th]:border-b-0 last:[&>td]:border-b-0";

/** Numeric value for a sortable WAPDate column. */
function sortValueFor(row: WapdateRow, key: string): SortValue {
  switch (key) {
    case "vp":
      return Number(row.victory_points);
    case "wins":
      return row.wins;
    case "pf":
      return Number(row.points_for);
    default:
      return null;
  }
}

/** The current period when there is one, otherwise the latest complete period. */
function defaultWapdatePeriod(periods: readonly WapdatePeriod[]): WapdatePeriod | null {
  const current = periods.find((period) => period.status === "current");
  if (current !== undefined) {
    return current;
  }
  return periods.reduce<WapdatePeriod | null>(
    (latest, period) => (latest === null || period.period > latest.period ? period : latest),
    null,
  );
}

function periodLabel(period: WapdatePeriod): string {
  const state = period.status === "current" ? "in progress" : "complete";
  return `Weeks ${period.start_week}-${period.end_week} · ${state}`;
}

export interface WapdateSectionProps {
  leagueId: number;
  season: number;
  dataVersion: number;
}

/**
 * WAPDate standings: the worst team in each fixed four-week period, lowest first by VP, then
 * wins, then points for. The period toggle lists only the periods the API offers and defaults to
 * the current period (or the latest complete one). Rows safe from last place in the current
 * period are greyed and carry a visible, accessible "Safe" marker, never colour alone.
 *
 * VP, wins, and points for sort on the client; the team column is not sortable. The team column is
 * pinned at the left edge with an opaque background so nothing shows through it while scrolling.
 */
export function WapdateSection({ leagueId, season, dataVersion }: WapdateSectionProps) {
  const { state, reload } = useWapdateData(leagueId, season, dataVersion);
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState | null>(null);

  const periods = state.status === "ready" ? state.wapdate.periods : [];
  const active =
    periods.find((period) => period.period === selectedPeriod) ?? defaultWapdatePeriod(periods);

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };
  const orderedRows = sortRows(active?.rows ?? [], sort, sortValueFor);

  return (
    <section aria-labelledby="h-wapdate" className="mt-7 md:mt-9">
      <h2 id="h-wapdate" className="text-base font-bold">
        WAPDate standings
      </h2>

      {state.status === "loading" ? <LoadingState label="Loading WAPDate standings…" /> : null}

      {state.status === "error" ? <ErrorState onRetry={reload} message={state.message} /> : null}

      {state.status === "empty" ? (
        <EmptyState
          title="No WAPDate periods yet"
          detail="WAPDate standings appear after the first completed week of a four-week period."
        />
      ) : null}

      {state.status === "ready" && active !== null ? (
        <>
          <fieldset className="mt-3">
            <legend className="sr-only">WAPDate period</legend>
            <div className="flex flex-wrap gap-2">
              {periods.map((period) => {
                const checked = active.period === period.period;
                return (
                  <label
                    key={period.period}
                    className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand-ink ${
                      checked
                        ? "border-brand-ink bg-brand-soft text-ink"
                        : "border-line bg-surface text-ink-muted hover:border-line-strong"
                    }`}
                  >
                    <input
                      type="radio"
                      name="wapdate-period"
                      value={period.period}
                      checked={checked}
                      onChange={() => setSelectedPeriod(period.period)}
                      className="h-4 w-4 accent-brand-ink"
                    />
                    <span>{periodLabel(period)}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <p className="mt-2 text-[13px] text-ink-faint">
            Weeks counted: {active.weeks.length === 0 ? "none" : active.weeks.join(", ")}.
          </p>

          <div className="relative mt-3">
            <div
              className="relative overflow-x-auto rounded-xl border border-line bg-surface"
              tabIndex={0}
              role="region"
              aria-label="WAPDate standings, scrollable horizontally"
            >
              <table className="w-full min-w-[420px] border-separate border-spacing-0 text-sm">
                <caption className="sr-only">
                  WAPDate standings for weeks {active.start_week}-{active.end_week},{" "}
                  {active.status === "current" ? "in progress" : "complete"}: team, victory points,
                  wins, and points for, lowest first.
                </caption>
                <thead>
                  <tr className="[&>th]:border-b [&>th]:border-line-strong">
                    <th
                      scope="col"
                      className={`${headCell} sticky left-0 z-20 min-w-[176px] bg-surface shadow-sticky`}
                    >
                      Team
                    </th>
                    <SortableHeader
                      label="VP"
                      sortKey="vp"
                      state={sort}
                      onSort={handleSort}
                      initialDirection="asc"
                      className={headCell}
                    />
                    <SortableHeader
                      label="Wins"
                      sortKey="wins"
                      state={sort}
                      onSort={handleSort}
                      initialDirection="asc"
                      className={headCell}
                    />
                    <SortableHeader
                      label="PF"
                      sortKey="pf"
                      state={sort}
                      onSort={handleSort}
                      initialDirection="asc"
                      className={headCell}
                    />
                  </tr>
                </thead>
                <tbody>
                  {orderedRows.map((row) => {
                    const stickyBackground = row.eliminated
                      ? "bg-surface-muted"
                      : "bg-surface group-hover:bg-surface-hover";
                    return (
                      <tr
                        key={row.team_id}
                        className={`group ${ROW_DIVIDER} ${
                          row.eliminated
                            ? "bg-surface-muted text-ink-faint"
                            : "hover:bg-surface-hover"
                        }`}
                      >
                        <th
                          scope="row"
                          className={`sticky left-0 z-10 min-w-[176px] px-3 py-2 text-left font-semibold shadow-sticky ${stickyBackground}`}
                        >
                          <span className="inline-flex flex-wrap items-center gap-2">
                            <span>{row.team_name}</span>
                            {row.eliminated ? (
                              <span
                                className="inline-flex items-center rounded-full border border-line-strong bg-surface-emphasis px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-strong"
                                title="cannot finish last"
                              >
                                Safe<span className="sr-only"> — cannot finish last</span>
                              </span>
                            ) : null}
                          </span>
                        </th>
                        <td className={`${numCell} font-bold`}>{formatVP(row.victory_points)}</td>
                        <td className={`${numCell} text-ink-subtle`}>{row.wins}</td>
                        <td className={`${numCell} text-ink-subtle`}>
                          {formatPoints(row.points_for)}
                        </td>
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
        </>
      ) : null}
    </section>
  );
}
