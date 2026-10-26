import type { ProbabilityInterval, TeamPlayoffOdds } from "../api/types";
import { SortableHeader } from "../components/SortableHeader";
import {
  sortRows,
  type SortDirection,
  type SortState,
  type SortValue,
} from "../components/sorting";
import { BODY_CELL_DIVIDER, LAST_ROW_NO_DIVIDER } from "../components/tableStyles";
import { intervalLabel, percentLabel, probabilityDescription } from "./playoffOddsFormat";

const headCell =
  "whitespace-nowrap border-b border-line-strong px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const numCell = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

function barWidth(value: string): number {
  return Math.min(100, Math.max(0, Number(value) * 100));
}

function sortValueFor(row: TeamPlayoffOdds, key: string): SortValue {
  switch (key) {
    case "playoff":
      return Number(row.playoff.probability);
    case "bye":
      return Number(row.bye.probability);
    default:
      return null;
  }
}

function ProbabilityCell({
  label,
  probability,
}: {
  label: string;
  probability: ProbabilityInterval;
}) {
  return (
    <td className={`${numCell} ${BODY_CELL_DIVIDER} align-top`}>
      <span aria-hidden="true" className="font-semibold text-ink">
        {percentLabel(probability.probability)}
      </span>
      <span
        aria-hidden="true"
        className="mt-1 block h-1.5 w-full min-w-[64px] overflow-hidden rounded-full bg-surface-emphasis"
      >
        <span
          className="block h-full rounded-full bg-brand"
          style={{ width: `${barWidth(probability.probability)}%` }}
        />
      </span>
      <span aria-hidden="true" className="hidden text-[11px] text-ink-faint sm:block">
        {intervalLabel(probability)}
      </span>
      <span className="sr-only">{probabilityDescription(label, probability)}</span>
    </td>
  );
}

export interface PlayoffOddsTableProps {
  rows: TeamPlayoffOdds[];
  sort: SortState;
  onSort: (key: string, initialDirection: SortDirection) => void;
}

/**
 * The playoff-odds table: team (pinned), division, playoff %, and bye %. Numeric columns sort on
 * the client; the team column keeps a stable name order and is never sortable. Every probability
 * has visible text, a decorative bar, a visible interval on wider screens, and a complete
 * screen-reader description, so colour is never the only signal.
 */
export function PlayoffOddsTable({ rows, sort, onSort }: PlayoffOddsTableProps) {
  const nameOrdered = rows
    .slice()
    .sort((left, right) => left.team_name.localeCompare(right.team_name));
  const orderedRows = sortRows(nameOrdered, sort, sortValueFor);

  return (
    <div className="relative mt-3">
      <div
        className="relative overflow-x-auto rounded-xl border border-line bg-surface"
        tabIndex={0}
        role="region"
        aria-label="Playoff odds, scrollable horizontally"
      >
        <table className="w-full min-w-[520px] border-separate border-spacing-0 text-sm">
          <caption className="sr-only">
            Playoff odds: team, division, playoff probability, and first-round bye probability, with
            the 95% interval for each estimate.
          </caption>
          <thead>
            <tr>
              <th
                scope="col"
                className={`${headCell} sticky left-0 z-20 min-w-[160px] bg-surface shadow-sticky`}
              >
                Team
              </th>
              <th scope="col" className={headCell}>
                Division
              </th>
              <SortableHeader
                label="Playoff %"
                sortKey="playoff"
                state={sort}
                onSort={onSort}
                initialDirection="desc"
                className={headCell}
              />
              <SortableHeader
                label="Bye %"
                sortKey="bye"
                state={sort}
                onSort={onSort}
                initialDirection="desc"
                className={headCell}
              />
            </tr>
          </thead>
          <tbody className={LAST_ROW_NO_DIVIDER}>
            {orderedRows.map((row) => (
              <tr key={row.team_id} className="group hover:bg-surface-hover">
                <th
                  scope="row"
                  className={`${BODY_CELL_DIVIDER} sticky left-0 z-10 min-w-[160px] bg-surface px-3 py-2 text-left font-semibold text-ink shadow-sticky group-hover:bg-surface-hover`}
                >
                  <span>{row.team_name}</span>
                  <span className="sr-only">
                    , {probabilityDescription("division title", row.division_title)}
                  </span>
                </th>
                <td className={`${numCell} ${BODY_CELL_DIVIDER} text-left text-ink-subtle`}>
                  {row.division}
                </td>
                <ProbabilityCell label="playoff" probability={row.playoff} />
                <ProbabilityCell label="first-round bye" probability={row.bye} />
              </tr>
            ))}
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
