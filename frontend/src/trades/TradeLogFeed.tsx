import { useMemo, useState } from "react";

import type { TradeItem } from "../api/types";
import { TradeCard } from "./TradeCard";

export interface TradeLogFeedProps {
  trades: TradeItem[];
  allTeams: string[];
  allYears: number[];
}

export function TradeLogFeed({ trades, allTeams, allYears }: TradeLogFeedProps) {
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const [yearFilter, setYearFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const hasActiveFilters =
    teamFilter !== "all" || yearFilter !== "all" || searchQuery.trim() !== "";

  const handleResetFilters = () => {
    setTeamFilter("all");
    setYearFilter("all");
    setSearchQuery("");
  };

  const filteredTrades = useMemo(() => {
    return [...trades]
      .sort((a, b) => new Date(b.trade_date).getTime() - new Date(a.trade_date).getTime())
      .filter((trade) => {
        // Team filter
        if (teamFilter !== "all") {
          const involvesTeam = trade.parties.some(
            (p) => p.team_name_raw.toLowerCase() === teamFilter.toLowerCase(),
          );
          if (!involvesTeam) return false;
        }

        // Draft year filter
        if (yearFilter !== "all") {
          const targetYear = Number(yearFilter);
          const hasYearInAgreement = trade.agreement_season === targetYear;
          const hasYearInParties = trade.parties.some(
            (p) =>
              p.auction_dollars.some((d) => d.draft_year === targetYear) ||
              p.draft_picks_sent.some((pick) => pick.draft_year === targetYear) ||
              p.draft_picks_received.some((pick) => pick.draft_year === targetYear),
          );
          const hasYearInConditions = trade.conditions.some((c) => c.draft_year === targetYear);
          if (!hasYearInAgreement && !hasYearInParties && !hasYearInConditions) {
            return false;
          }
        }

        // Search query filter (trade ID, summary, or player name)
        if (searchQuery.trim() !== "") {
          const q = searchQuery.toLowerCase();
          const matchesId = trade.external_trade_id.toLowerCase().includes(q);
          const matchesSummary = trade.summary.toLowerCase().includes(q);
          const matchesPlayer = trade.parties.some(
            (p) =>
              p.players_sent.some((player) => JSON.stringify(player).toLowerCase().includes(q)) ||
              p.players_received.some((player) => JSON.stringify(player).toLowerCase().includes(q)),
          );
          if (!matchesId && !matchesSummary && !matchesPlayer) {
            return false;
          }
        }

        return true;
      });
  }, [trades, teamFilter, yearFilter, searchQuery]);

  return (
    <section aria-labelledby="trade-log-heading" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <h2 id="trade-log-heading" className="text-base font-bold text-ink">
            Trade Log
          </h2>
          <span className="inline-flex items-center rounded-full bg-surface-strong px-2.5 py-0.5 text-xs font-semibold text-ink-muted">
            {filteredTrades.length} {filteredTrades.length === 1 ? "trade" : "trades"}
          </span>
        </div>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={handleResetFilters}
            className="text-xs font-medium text-brand-ink hover:underline"
          >
            Reset filters
          </button>
        )}
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface p-3">
        {/* Team Filter */}
        <div className="flex flex-1 min-w-[140px] items-center gap-1.5">
          <label htmlFor="filter-team" className="text-xs font-semibold text-ink-faint">
            Team:
          </label>
          <select
            id="filter-team"
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            className="w-full rounded border border-line bg-surface px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none"
          >
            <option value="all">All Teams</option>
            {allTeams.map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
        </div>

        {/* Draft Year Filter */}
        <div className="flex flex-1 min-w-[130px] items-center gap-1.5">
          <label htmlFor="filter-year" className="text-xs font-semibold text-ink-faint">
            Draft Year:
          </label>
          <select
            id="filter-year"
            value={yearFilter}
            onChange={(e) => setYearFilter(e.target.value)}
            className="w-full rounded border border-line bg-surface px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none"
          >
            <option value="all">All Draft Years</option>
            {allYears.map((year) => (
              <option key={year} value={String(year)}>
                {year} Draft
              </option>
            ))}
          </select>
        </div>

        {/* Search Query */}
        <div className="flex flex-1 min-w-[160px] items-center gap-1.5">
          <label htmlFor="filter-search" className="text-xs font-semibold text-ink-faint">
            Search:
          </label>
          <input
            id="filter-search"
            type="text"
            placeholder="Player, team, or notes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-line bg-surface px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none"
          />
        </div>
      </div>

      {/* Trade Feed */}
      {filteredTrades.length === 0 ? (
        <div className="rounded-lg border border-line bg-surface p-8 text-center">
          <p className="text-sm font-semibold text-ink">No trades match your filters</p>
          <p className="mt-1 text-xs text-ink-muted">
            Try adjusting your team or draft year filter, or resetting search filters.
          </p>
          <button
            type="button"
            onClick={handleResetFilters}
            className="mt-3 inline-flex items-center rounded bg-surface-strong px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-emphasis"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredTrades.map((trade) => (
            <TradeCard key={trade.id || trade.external_trade_id} trade={trade} />
          ))}
        </div>
      )}
    </section>
  );
}
