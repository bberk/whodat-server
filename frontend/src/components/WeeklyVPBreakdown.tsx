import type { WeeklyBreakdownRow } from "../standings/model";
import { formatVP, vpTone, vpToneClass } from "./format";
import { seriesStyle } from "./series";

export interface WeeklyVPBreakdownProps {
  weeks: number[];
  selectedWeek: number;
  onSelectWeek: (week: number) => void;
  rows: WeeklyBreakdownRow[];
  note: string | null;
  selectedTeamId: number | null;
}

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

/**
 * One week's VP per team, plus the cumulative total through that week. The API exposes weekly and
 * cumulative VP totals; it does not expose the per-component split, so this table shows exactly
 * the values the server returns.
 */
export function WeeklyVPBreakdown({
  weeks,
  selectedWeek,
  onSelectWeek,
  rows,
  note,
  selectedTeamId,
}: WeeklyVPBreakdownProps) {
  return (
    <>
      <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Select week">
        {weeks.map((week) => {
          const active = week === selectedWeek;
          return (
            <button
              key={week}
              type="button"
              aria-pressed={active}
              onClick={() => onSelectWeek(week)}
              className={`rounded-full border px-3.5 py-1 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                active
                  ? "border-brand bg-brand text-brand-foreground"
                  : "border-gray-200 bg-white text-gray-700 hover:border-brand"
              }`}
            >
              W{week}
            </button>
          );
        })}
      </div>
      <div className="relative mt-3">
        <div
          className="relative overflow-x-auto rounded-xl border border-gray-200 bg-white"
          tabIndex={0}
          role="region"
          aria-label={`Week ${selectedWeek} VP breakdown, scrollable horizontally`}
        >
          <table className="w-full min-w-[420px] border-collapse text-sm">
            <caption className="sr-only">
              Week {selectedWeek} victory points per team, with cumulative VP through that week.
            </caption>
            <thead>
              <tr className="border-b border-gray-300">
                <th scope="col" className={`${headCell} sticky left-0 z-20 min-w-[148px] bg-white`}>
                  Team
                </th>
                <th scope="col" className={`${headCell} text-right`}>
                  Weekly VP
                </th>
                <th scope="col" className={`${headCell} text-right`}>
                  Cumulative VP
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const selected = row.teamId === selectedTeamId;
                const style = seriesStyle(row.styleIndex);
                return (
                  <tr
                    key={row.teamId}
                    className={`border-b border-gray-200 last:border-b-0 ${
                      selected ? "bg-brand-foreground" : ""
                    }`}
                  >
                    <th
                      scope="row"
                      className={`sticky left-0 z-10 min-w-[148px] px-3 py-2 text-left font-semibold ${
                        selected ? "bg-brand-foreground" : "bg-white"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="inline-flex h-5 w-5 flex-none items-center justify-center rounded-md border text-[11px] font-bold"
                          style={{ color: style.color, borderColor: style.color }}
                        >
                          {row.teamName.charAt(0)}
                        </span>
                        {row.teamName}
                      </span>
                    </th>
                    <td className={`${numCell} font-bold ${vpToneClass(vpTone(row.weekly))}`}>
                      {formatVP(row.weekly)}
                    </td>
                    <td className={`${numCell} text-gray-600`}>{formatVP(row.cumulative)}</td>
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
      </div>
      {note === null ? null : (
        <p className="mt-2.5 rounded-lg border border-teal-200 bg-brand-foreground px-3 py-2 text-[13px] text-gray-700">
          {note}
        </p>
      )}
    </>
  );
}
