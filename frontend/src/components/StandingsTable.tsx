import type { StandingsRow } from "../api/types";
import { formatPoints, formatRecord, formatVP, vpTone, vpToneClass } from "./format";
import { seriesStyle } from "./series";

export interface StandingsTableProps {
  /** Visually hidden description of the table (screen-reader caption). */
  caption: string;
  /** Accessible name for the horizontal scroll region. */
  ariaLabel: string;
  rows: StandingsRow[];
  weeks: number[];
  showTies: boolean;
  selectedTeamId: number | null;
  onSelectTeam: (teamId: number) => void;
  seriesIndexByTeamId: ReadonlyMap<number, number>;
}

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

/**
 * The standings table, reused for the overall table and for each division. The rank cell renders
 * `row.rank` exactly as the data layer supplies it and this component never ranks or re-ranks: for
 * a division table that value is the team's overall league rank (a division only groups/filters
 * rows). Wide content scrolls inside its own region with the rank and team columns pinned; the
 * team cell is a button so selecting a team is keyboard operable.
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
  return (
    <div className="relative mt-3">
      {/* `relative` keeps any absolutely positioned descendant (for example a visually hidden
          label) inside this scroll container; without it such a box escapes the clip and makes
          the whole page scroll sideways at narrow widths. */}
      <div
        className="relative overflow-x-auto rounded-xl border border-gray-200 bg-white"
        tabIndex={0}
        role="region"
        aria-label={ariaLabel}
      >
        <table className="w-full min-w-[700px] border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-gray-300">
              <th scope="col" className={`${headCell} sticky left-0 z-20 w-[46px] bg-white`}>
                #
              </th>
              <th
                scope="col"
                className={`${headCell} sticky left-[46px] z-20 min-w-[148px] bg-white shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]`}
              >
                Team
              </th>
              <th scope="col" className={headCell}>
                Owner
              </th>
              <th scope="col" className={`${headCell} text-right`}>
                Season VP
              </th>
              <th scope="col" className={`${headCell} text-right`}>
                {showTies ? "W-L-T" : "W-L"}
              </th>
              <th scope="col" className={`${headCell} text-right`}>
                Points for
              </th>
              {weeks.map((week) => (
                <th
                  key={week}
                  scope="col"
                  aria-label={`Week ${week} VP`}
                  className={`${headCell} text-right`}
                >
                  W{week}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const selected = row.team_id === selectedTeamId;
              const stickyBackground = selected ? "bg-brand-foreground" : "bg-white";
              const style = seriesStyle(seriesIndexByTeamId.get(row.team_id) ?? 0);
              return (
                <tr
                  key={row.team_id}
                  className={`border-b border-gray-200 last:border-b-0 ${
                    selected ? "bg-brand-foreground" : "hover:bg-gray-50"
                  }`}
                >
                  <th
                    scope="row"
                    className={`${numCell} sticky left-0 z-10 w-[46px] text-left font-normal text-gray-600 ${stickyBackground} ${
                      selected ? "shadow-[inset_3px_0_0_0_#0f766e]" : ""
                    }`}
                  >
                    {row.rank}
                  </th>
                  <td
                    className={`sticky left-[46px] z-10 min-w-[148px] px-3 py-2 shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)] ${stickyBackground}`}
                  >
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelectTeam(row.team_id)}
                      className="flex w-full items-center gap-2 rounded text-left font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
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
                  </td>
                  <td className={`${numCell} text-left text-gray-600`}>{row.owner_name ?? "—"}</td>
                  <td className={`${numCell} font-bold ${vpToneClass(vpTone(row.victory_points))}`}>
                    {formatVP(row.victory_points)}
                  </td>
                  <td className={`${numCell} text-gray-600`}>{formatRecord(row, showTies)}</td>
                  <td className={`${numCell} text-gray-600`}>{formatPoints(row.points_for)}</td>
                  {row.weekly_vp.map((vp, index) => (
                    <td
                      key={`week-${index}`}
                      className={`${numCell} font-medium ${vpToneClass(vpTone(vp))}`}
                    >
                      {formatVP(vp)}
                    </td>
                  ))}
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
        Table scrolls sideways — rank and team stay pinned.
      </p>
    </div>
  );
}
