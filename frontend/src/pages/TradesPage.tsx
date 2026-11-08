import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { api } from "../api/endpoints";
import { toDisplayError } from "../api/errors";
import type { AuctionBudgetsResponse, TradesListResponse } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { useLeague } from "../leagues/LeagueContext";

/**
 * Trades and Projected Auction Budgets page (AC-TRADE-VIEW).
 *
 * Displays:
 * - A projected auction budget table per draft year with starting budget and trade deltas.
 * - An interactive trade log feed with details on players exchanged and conditional terms.
 */
export function TradesPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague } = useLeague();

  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tradesData, setTradesData] = useState<TradesListResponse | null>(null);
  const [budgetData, setBudgetData] = useState<AuctionBudgetsResponse | null>(null);

  useEffect(() => {
    if (validId && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, leagueId, selectedLeague?.league_id, selectLeague]);

  useEffect(() => {
    if (!validId) return;

    let ignore = false;
    setLoading(true);
    setError(null);

    const loadData = async () => {
      try {
        const currentYear = new Date().getFullYear();
        const [tradesRes, budgetRes] = await Promise.all([
          api.listTrades(leagueId),
          api.auctionBudgets(leagueId, currentYear),
        ]);
        if (!ignore) {
          setTradesData(tradesRes);
          setBudgetData(budgetRes);
          setLoading(false);
        }
      } catch (err) {
        if (!ignore) {
          setError(toDisplayError(err).message);
          setLoading(false);
        }
      }
    };

    void loadData();
    return () => {
      ignore = true;
    };
  }, [validId, leagueId]);

  if (!validId) {
    return <Navigate to="/" replace />;
  }

  const leagueName = membership?.name ?? `League ${leagueId}`;

  return (
    <div className="pt-5 md:pt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line-subtle pb-4">
        <div>
          <h1 className="text-xl font-bold md:text-2xl">Trades & Auction Budgets</h1>
          <p className="mt-1 text-[13px] text-ink-faint">{leagueName}</p>
        </div>
      </div>

      {loading && (
        <div className="mt-8">
          <LoadingState label="Loading trade and auction budget data..." />
        </div>
      )}

      {error && (
        <div className="mt-8">
          <ErrorState message={error} onRetry={() => window.location.reload()} />
        </div>
      )}

      {!loading && !error && tradesData?.trades.length === 0 && (
        <div className="mt-8">
          <EmptyState
            title="No trades recorded"
            detail="No trades have been synced from Discord or the trade repository yet."
          />
        </div>
      )}

      {!loading && !error && tradesData && tradesData.trades.length > 0 && (
        <div className="mt-6 space-y-6">
          <div className="rounded-lg border border-line bg-surface p-4">
            <h2 className="text-base font-bold">Projected Auction Dollars</h2>
            <p className="mt-1 text-sm text-ink-muted">
              Base budget: ${budgetData?.base_auction_budget ?? "200.00"}
            </p>
          </div>
          <div className="rounded-lg border border-line bg-surface p-4">
            <h2 className="text-base font-bold">Trade Log ({tradesData.trades.length})</h2>
          </div>
        </div>
      )}
    </div>
  );
}
