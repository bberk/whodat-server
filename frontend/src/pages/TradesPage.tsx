import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { api } from "../api/endpoints";
import { toDisplayError } from "../api/errors";
import type { AuctionBudgetsResponse, TradesListResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { useLeague } from "../leagues/LeagueContext";
import { DraftYearTabs } from "../trades/DraftYearTabs";
import { ProjectedAuctionTable } from "../trades/ProjectedAuctionTable";
import { TradeLogFeed } from "../trades/TradeLogFeed";

/**
 * Extract all unique draft years involved in trades and ensure upcoming seasons are included.
 */
function extractAvailableYears(trades: TradesListResponse | null): number[] {
  const currentYear = new Date().getFullYear();
  const years = new Set<number>([currentYear, currentYear + 1, currentYear + 2]);

  if (trades) {
    for (const trade of trades.trades) {
      if (trade.agreement_season) years.add(trade.agreement_season);
      for (const party of trade.parties) {
        for (const b of party.auction_dollars) {
          if (b.draft_year) years.add(b.draft_year);
        }
        for (const p of party.draft_picks_sent) {
          if (p.draft_year && typeof p.draft_year === "number") years.add(p.draft_year);
        }
        for (const p of party.draft_picks_received) {
          if (p.draft_year && typeof p.draft_year === "number") years.add(p.draft_year);
        }
      }
      for (const cond of trade.conditions) {
        if (cond.draft_year && typeof cond.draft_year === "number") {
          years.add(cond.draft_year);
        }
      }
    }
  }

  return Array.from(years).sort((a, b) => a - b);
}

/**
 * Trades and Projected Auction Budgets page (AC-TRADE-VIEW).
 *
 * Displays:
 * - A projected auction budget table per draft year with starting budget and trade deltas.
 * - An interactive trade log feed with details on players exchanged and conditional terms.
 * - Admin fast-sync capability directly from the trade feed header.
 */
export function TradesPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague } = useLeague();
  const { user } = useAuth();

  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);
  const isAdmin = user?.role === "admin";

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tradesData, setTradesData] = useState<TradesListResponse | null>(null);
  const [budgetsByYear, setBudgetsByYear] = useState<Record<number, AuctionBudgetsResponse>>({});
  const [budgetLoading, setBudgetLoading] = useState(false);

  // Sync state for admins
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const currentYear = useMemo(() => new Date().getFullYear(), []);
  const availableYears = useMemo(() => extractAvailableYears(tradesData), [tradesData]);
  const [selectedYear, setSelectedYear] = useState<number>(currentYear);

  useEffect(() => {
    if (validId && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, leagueId, selectedLeague?.league_id, selectLeague]);

  const loadData = useCallback(async () => {
    if (!validId) return;

    setLoading(true);
    setError(null);

    try {
      const [tradesRes, budgetRes] = await Promise.all([
        api.listTrades(leagueId),
        api.auctionBudgets(leagueId, selectedYear),
      ]);
      setTradesData(tradesRes);
      setBudgetsByYear((prev) => ({
        ...prev,
        [selectedYear]: budgetRes,
      }));
      setLoading(false);
    } catch (err) {
      setError(toDisplayError(err).message);
      setLoading(false);
    }
  }, [validId, leagueId, selectedYear]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Load budgets for a newly selected draft year if not cached yet
  const handleSelectYear = async (year: number) => {
    setSelectedYear(year);
    if (!validId || budgetsByYear[year]) return;

    setBudgetLoading(true);
    try {
      const res = await api.auctionBudgets(leagueId, year);
      setBudgetsByYear((prev) => ({
        ...prev,
        [year]: res,
      }));
    } catch (err) {
      setError(toDisplayError(err).message);
    } finally {
      setBudgetLoading(false);
    }
  };

  const handleAdminSync = async () => {
    if (!validId || isSyncing) return;

    setIsSyncing(true);
    setSyncNotice(null);
    setSyncError(null);

    try {
      const result = await api.syncTradeRepo(leagueId);
      setSyncNotice(
        `Successfully synced ${result.trades_synced} ${
          result.trades_synced === 1 ? "trade" : "trades"
        } from GitHub repository.`,
      );
      // Reload both trades and active draft year budgets
      const [tradesRes, budgetRes] = await Promise.all([
        api.listTrades(leagueId),
        api.auctionBudgets(leagueId, selectedYear),
      ]);
      setTradesData(tradesRes);
      setBudgetsByYear((prev) => ({
        ...prev,
        [selectedYear]: budgetRes,
      }));
    } catch (err) {
      setSyncError(toDisplayError(err).message);
    } finally {
      setIsSyncing(false);
    }
  };

  // Collect all unique team names across trades and projections
  const allTeams = useMemo(() => {
    const teams = new Set<string>();
    if (tradesData) {
      for (const t of tradesData.trades) {
        for (const p of t.parties) {
          if (p.team_name_raw) teams.add(p.team_name_raw);
        }
      }
    }
    const currentProjections = budgetsByYear[selectedYear]?.projections;
    if (currentProjections) {
      for (const proj of currentProjections) {
        if (proj.team_id) teams.add(proj.team_id);
      }
    }
    return Array.from(teams).sort((a, b) => a.localeCompare(b));
  }, [tradesData, budgetsByYear, selectedYear]);

  if (!validId) {
    return <Navigate to="/" replace />;
  }

  const leagueName = membership?.name ?? `League ${leagueId}`;
  const currentBudget = budgetsByYear[selectedYear];

  return (
    <div className="space-y-6 pt-5 md:pt-6">
      {/* Page Header */}
      <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-line-subtle pb-4">
        <div>
          <h1 className="text-xl font-bold text-ink md:text-2xl">Trades & Auction Budgets</h1>
          <p className="mt-1 text-xs text-ink-faint md:text-sm">{leagueName}</p>
        </div>

        {isAdmin && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={isSyncing}
              onClick={handleAdminSync}
              className={`inline-flex items-center rounded-md border border-line-strong bg-surface px-3 py-1.5 text-xs font-semibold text-ink shadow-sm transition hover:bg-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand ${
                isSyncing ? "cursor-wait opacity-60" : ""
              }`}
            >
              {isSyncing ? "Syncing Trades..." : "Sync Trades from GitHub"}
            </button>
          </div>
        )}
      </div>

      {/* Sync Notices */}
      {syncNotice && (
        <div
          role="status"
          className="flex items-center justify-between rounded-lg border border-brand-soft-line bg-brand-soft p-3 text-xs text-brand-ink"
        >
          <span>{syncNotice}</span>
          <button
            type="button"
            onClick={() => setSyncNotice(null)}
            className="text-xs font-bold hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {syncError && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-lg border border-danger-line bg-danger-surface p-3 text-xs text-danger-ink"
        >
          <span>{syncError}</span>
          <button
            type="button"
            onClick={() => setSyncError(null)}
            className="text-xs font-bold hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Primary Loading & Error States */}
      {loading && (
        <div className="mt-8">
          <LoadingState label="Loading trade and auction budget data..." />
        </div>
      )}

      {error && !loading && (
        <div className="mt-8">
          <ErrorState message={error} onRetry={() => void loadData()} />
        </div>
      )}

      {/* Empty State when no trades have been recorded */}
      {!loading && !error && tradesData?.trades.length === 0 && (
        <div className="mt-8">
          <EmptyState
            title="No trades recorded"
            detail="No trades have been synced from Discord or the trade repository yet. Check back once trades are announced and approved."
          />
        </div>
      )}

      {/* Content View */}
      {!loading && !error && tradesData && tradesData.trades.length > 0 && (
        <div className="space-y-8">
          {/* Draft Year Selector Tabs */}
          <DraftYearTabs
            years={availableYears}
            selectedYear={selectedYear}
            onSelectYear={handleSelectYear}
            isLoading={budgetLoading}
          />

          {/* Projected Auction Dollars Table */}
          {currentBudget && (
            <ProjectedAuctionTable
              draftYear={selectedYear}
              baseBudget={currentBudget.base_auction_budget}
              projections={currentBudget.projections}
              isLoading={budgetLoading}
            />
          )}

          {/* Interactive Trade Log Feed */}
          <TradeLogFeed trades={tradesData.trades} allTeams={allTeams} allYears={availableYears} />
        </div>
      )}
    </div>
  );
}
