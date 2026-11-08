import { useMemo, useState } from "react";

import type { TeamBudgetProjectionItem } from "../api/types";
import { InfoTooltip } from "../components/InfoTooltip";
import { SortableHeader } from "../components/SortableHeader";
import { toggleSort, type SortDirection, type SortState } from "../components/sorting";
import { BODY_CELL_DIVIDER, LAST_ROW_NO_DIVIDER } from "../components/tableStyles";
import { dollarBadgeClass, dollarTone, dollarToneClass, formatAuctionDollars } from "./format";

export interface ProjectedAuctionTableProps {
  draftYear: number;
  baseBudget: string;
  projections: TeamBudgetProjectionItem[];
  isLoading?: boolean;
}

const headCell =
  "whitespace-nowrap border-b border-line-strong px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const numHeadCell =
  "whitespace-nowrap border-b border-line-strong px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const bodyCell = "whitespace-nowrap px-3 py-2.5 text-sm";
const numBodyCell = "whitespace-nowrap px-3 py-2.5 text-right font-mono text-sm tabular-nums";

const STICKY_TEAM_HEAD =
  "sticky left-0 z-20 bg-surface shadow-sticky border-r border-line-subtle min-w-[130px] md:min-w-[170px]";
const STICKY_TEAM_CELL =
  "sticky left-0 z-10 bg-surface shadow-sticky border-r border-line-subtle min-w-[130px] md:min-w-[170px]";

export function ProjectedAuctionTable({
  draftYear,
  baseBudget,
  projections,
  isLoading = false,
}: ProjectedAuctionTableProps) {
  const [sort, setSort] = useState<SortState | null>({
    key: "projected",
    direction: "desc",
  });

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  const sortedRows = useMemo(() => {
    if (!sort) return projections;
    return [...projections].sort((a, b) => {
      let cmp = 0;
      switch (sort.key) {
        case "team":
          cmp = a.team_id.localeCompare(b.team_id);
          break;
        case "base_delta":
          cmp = Number(a.base_trade_delta) - Number(b.base_trade_delta);
          break;
        case "net_delta":
          cmp = Number(a.net_delta) - Number(b.net_delta);
          break;
        case "projected":
          cmp = Number(a.projected_budget) - Number(b.projected_budget);
          break;
        default:
          break;
      }
      return sort.direction === "asc" ? cmp : -cmp;
    });
  }, [projections, sort]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-ink">
            Projected Auction Dollars — {draftYear} Draft
          </h2>
          <p className="text-xs text-ink-muted">
            Base league budget:{" "}
            <span className="font-semibold text-ink">{formatAuctionDollars(baseBudget)}</span>.
            Deltas reflect agreed trades and fulfilled conditions.
          </p>
        </div>
        {isLoading && (
          <span className="text-xs italic text-ink-faint">Updating projections...</span>
        )}
      </div>

      <div
        role="region"
        aria-label={`Projected Auction Budgets for ${draftYear}`}
        tabIndex={0}
        className="overflow-x-auto rounded-lg border border-line bg-surface"
      >
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Projected auction budgets for the {draftYear} fantasy football draft, by team
          </caption>
          <thead>
            <tr>
              <th scope="col" className={`${headCell} w-10 text-center`}>
                #
              </th>
              <SortableHeader
                label="Team"
                sortKey="team"
                state={sort}
                onSort={handleSort}
                initialDirection="asc"
                className={`${headCell} ${STICKY_TEAM_HEAD}`}
              />
              <th scope="col" className={numHeadCell}>
                Base
              </th>
              <SortableHeader
                label="Trade Delta"
                sortKey="base_delta"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={numHeadCell}
              />
              <th scope="col" className={numHeadCell}>
                Conditions
              </th>
              <SortableHeader
                label="Net Delta"
                sortKey="net_delta"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={numHeadCell}
              />
              <SortableHeader
                label="Projected Budget"
                sortKey="projected"
                state={sort}
                onSort={handleSort}
                initialDirection="desc"
                className={numHeadCell}
              />
            </tr>
          </thead>
          <tbody className={LAST_ROW_NO_DIVIDER}>
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-ink-muted">
                  No teams found for auction budget projection.
                </td>
              </tr>
            ) : (
              sortedRows.map((row, index) => {
                const baseTone = dollarTone(row.base_trade_delta);
                const netTone = dollarTone(row.net_delta);
                const hasFulfilled =
                  row.fulfilled_conditional_delta !== "0.00" &&
                  row.fulfilled_conditional_delta !== "0";
                const hasPending =
                  row.pending_conditional_delta !== "0.00" && row.pending_conditional_delta !== "0";

                return (
                  <tr key={row.team_id} className="hover:bg-surface-hover transition-colors">
                    <td
                      className={`${bodyCell} ${BODY_CELL_DIVIDER} w-10 text-center text-xs text-ink-faint`}
                    >
                      {index + 1}
                    </td>
                    <td
                      className={`${bodyCell} ${BODY_CELL_DIVIDER} ${STICKY_TEAM_CELL} font-medium text-ink`}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="truncate" title={row.team_id}>
                          {row.team_id}
                        </span>
                        {row.is_negative_budget && (
                          <span
                            className="inline-flex shrink-0 items-center rounded bg-danger-surface px-1.5 py-0.5 text-[10px] font-bold text-danger-ink border border-danger-line"
                            title="Projected budget is negative"
                          >
                            Deficit
                          </span>
                        )}
                      </div>
                    </td>
                    <td className={`${numBodyCell} ${BODY_CELL_DIVIDER} text-ink-muted`}>
                      {formatAuctionDollars(row.starting_budget)}
                    </td>
                    <td className={`${numBodyCell} ${BODY_CELL_DIVIDER}`}>
                      <span className={dollarToneClass(baseTone)}>
                        {formatAuctionDollars(row.base_trade_delta, { showPlus: true })}
                      </span>
                    </td>
                    <td className={`${numBodyCell} ${BODY_CELL_DIVIDER}`}>
                      {hasFulfilled || hasPending ? (
                        <div className="inline-flex items-center justify-end gap-1">
                          {hasFulfilled && (
                            <span
                              className={`rounded px-1.5 py-0.2 text-xs font-semibold ${dollarBadgeClass(
                                dollarTone(row.fulfilled_conditional_delta),
                              )}`}
                              title={`Fulfilled condition: ${formatAuctionDollars(
                                row.fulfilled_conditional_delta,
                                { showPlus: true },
                              )}`}
                            >
                              {formatAuctionDollars(row.fulfilled_conditional_delta, {
                                showPlus: true,
                              })}
                            </span>
                          )}
                          {hasPending && (
                            <span
                              className="rounded border border-warning-line bg-warning-surface px-1.5 py-0.2 text-xs font-semibold text-warning-ink"
                              title={`Pending condition: ${formatAuctionDollars(
                                row.pending_conditional_delta,
                                { showPlus: true },
                              )}`}
                            >
                              {formatAuctionDollars(row.pending_conditional_delta, {
                                showPlus: true,
                              })}{" "}
                              (P)
                            </span>
                          )}
                          <InfoTooltip
                            label={`Conditions for ${row.team_id}`}
                            text={`Fulfilled: ${formatAuctionDollars(
                              row.fulfilled_conditional_delta,
                              { showPlus: true },
                            )} | Pending: ${formatAuctionDollars(row.pending_conditional_delta, {
                              showPlus: true,
                            })}`}
                          />
                        </div>
                      ) : (
                        <span className="text-ink-faint">$0.00</span>
                      )}
                    </td>
                    <td className={`${numBodyCell} ${BODY_CELL_DIVIDER}`}>
                      <span
                        className={`inline-block rounded px-2 py-0.5 text-xs font-bold ${dollarBadgeClass(
                          netTone,
                        )}`}
                      >
                        {formatAuctionDollars(row.net_delta, { showPlus: true })}
                      </span>
                    </td>
                    <td
                      className={`${numBodyCell} ${BODY_CELL_DIVIDER} font-bold text-base text-ink`}
                    >
                      <span className={row.is_negative_budget ? "text-danger-ink" : "text-ink"}>
                        {formatAuctionDollars(row.projected_budget)}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
