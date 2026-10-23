import type { EloTeam } from "../api/types";
import { formatEloChange, formatEloValue, formatEloWhole } from "./format";
import { sortedEloTeams, teamDisplayName } from "../history/model";

export interface EloRatingsTableProps {
  teams: readonly EloTeam[];
  selectedTeamKey: string | null;
  onSelectTeam: (teamKey: string) => void;
}

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";

/** Format a peak/low reference as a short "season Wweek" label, or "start". */
function referenceLabel(reference: { season: number; week: number } | null): string {
  return reference === null ? "start" : `${reference.season} W${reference.week}`;
}

/**
 * Current Elo scores, highest first.
 *
 * The Elo score is rounded to a whole number; week and season changes keep two decimals and an
 * explicit sign. Peak and low name the week they happened (or "start"). Wide content scrolls
 * inside the region with the rank and team columns pinned, so the page body never scrolls
 * sideways at 360px. Selecting a row highlights that franchise in the chart.
 */
export function EloRatingsTable({ teams, selectedTeamKey, onSelectTeam }: EloRatingsTableProps) {
  const ordered = sortedEloTeams(teams);
  return (
    <div
      className="relative mt-3 overflow-x-auto rounded-xl border border-gray-200 bg-white"
      tabIndex={0}
      role="region"
      aria-label="Elo score history current scores, scrollable horizontally"
    >
      <table className="w-full min-w-[760px] border-collapse text-left text-[13px]">
        <caption className="sr-only">
          Current Elo scores sorted by current score, with change over the last week, change this
          season, peak, low, and owner.
        </caption>
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            <th scope="col" className={`${headCell} sticky left-0 z-20 w-11 bg-gray-50 text-right`}>
              #
            </th>
            <th
              scope="col"
              className={`${headCell} sticky left-11 z-20 min-w-[150px] bg-gray-50 shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]`}
            >
              Team
            </th>
            <th scope="col" className={`${headCell} text-right`}>
              Elo score
            </th>
            <th scope="col" className={`${headCell} text-right`}>
              Last week
            </th>
            <th scope="col" className={`${headCell} text-right`}>
              This season
            </th>
            <th scope="col" className={`${headCell} text-right`}>
              Peak
            </th>
            <th scope="col" className={`${headCell} text-right`}>
              Low
            </th>
            <th scope="col" className={headCell}>
              Owner
            </th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((team, index) => {
            const selected = team.team_key === selectedTeamKey;
            const name = teamDisplayName(team, teams);
            return (
              <tr
                key={team.team_key}
                className={`border-b border-gray-100 last:border-0 ${
                  selected ? "bg-brand-foreground" : ""
                }`}
              >
                <th
                  scope="row"
                  className="sticky left-0 z-10 w-11 bg-inherit px-3 py-2 text-right font-semibold tabular-nums text-gray-500"
                >
                  {index + 1}
                </th>
                <td
                  className={`sticky left-11 z-10 min-w-[150px] px-3 py-2 shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)] ${
                    selected ? "bg-brand-foreground" : "bg-white"
                  }`}
                >
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
