import { useState } from "react";

import type { WapdatePeriod } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { formatPoints, formatVP } from "../components/format";
import { useWapdateData } from "./useWapdateData";

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

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
 */
export function WapdateSection({ leagueId, season, dataVersion }: WapdateSectionProps) {
  const { state, reload } = useWapdateData(leagueId, season, dataVersion);
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null);

  const periods = state.status === "ready" ? state.wapdate.periods : [];
  const active =
    periods.find((period) => period.period === selectedPeriod) ?? defaultWapdatePeriod(periods);

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
                    className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand ${
                      checked
                        ? "border-brand bg-brand-foreground text-gray-900"
                        : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="wapdate-period"
                      value={period.period}
                      checked={checked}
                      onChange={() => setSelectedPeriod(period.period)}
                      className="h-4 w-4 accent-brand"
                    />
                    <span>{periodLabel(period)}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <p className="mt-2 text-[13px] text-gray-500">
            Weeks counted: {active.weeks.length === 0 ? "none" : active.weeks.join(", ")}.
          </p>

          <div className="relative mt-3">
            <div
              className="relative overflow-x-auto rounded-xl border border-gray-200 bg-white"
              tabIndex={0}
              role="region"
              aria-label="WAPDate standings, scrollable horizontally"
            >
              <table className="w-full min-w-[420px] border-collapse text-sm">
                <caption className="sr-only">
                  WAPDate standings for weeks {active.start_week}-{active.end_week},{" "}
                  {active.status === "current" ? "in progress" : "complete"}: team, victory points,
                  wins, and points for, lowest first.
                </caption>
                <thead>
                  <tr className="border-b border-gray-300">
                    <th
                      scope="col"
                      className={`${headCell} sticky left-0 z-20 min-w-[168px] bg-white shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]`}
                    >
                      Team
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      VP
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Wins
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      PF
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {active.rows.map((row) => {
                    const stickyBackground = row.eliminated ? "bg-gray-50" : "bg-white";
                    return (
                      <tr
                        key={row.team_id}
                        className={`border-b border-gray-200 last:border-b-0 ${
                          row.eliminated ? "bg-gray-50 text-gray-500" : "hover:bg-gray-50"
                        }`}
                      >
                        <th
                          scope="row"
                          className={`sticky left-0 z-10 min-w-[168px] px-3 py-2 text-left font-semibold shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)] ${stickyBackground}`}
                        >
                          <span className="inline-flex flex-wrap items-center gap-2">
                            <span>{row.team_name}</span>
                            {row.eliminated ? (
                              <span
                                className="inline-flex items-center rounded-full border border-gray-300 bg-gray-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-800"
                                title="cannot finish last"
                              >
                                Safe<span className="sr-only"> — cannot finish last</span>
                              </span>
                            ) : null}
                          </span>
                        </th>
                        <td className={`${numCell} font-bold`}>{formatVP(row.victory_points)}</td>
                        <td className={`${numCell} text-gray-600`}>{row.wins}</td>
                        <td className={`${numCell} text-gray-600`}>
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
              className="pointer-events-none absolute inset-y-0 right-0 w-7 rounded-r-xl bg-gradient-to-l from-gray-900/5 to-transparent"
            />
            <p aria-hidden="true" className="mt-1.5 px-0.5 text-xs text-gray-500">
              Table scrolls sideways — team stays pinned.
            </p>
          </div>
        </>
      ) : null}
    </section>
  );
}
