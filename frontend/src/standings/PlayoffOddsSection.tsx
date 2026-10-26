import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { toggleSort, type SortDirection, type SortState } from "../components/sorting";
import { PLAYOFF_ODDS_UNAVAILABLE_COPY } from "./playoffOddsCopy";
import { PlayoffOddsTable } from "./PlayoffOddsTable";
import { usePlayoffOdds } from "./usePlayoffOdds";

function sortLabel(sort: SortState): string {
  const column = sort.key === "bye" ? "Bye %" : "Playoff %";
  return `sorted by ${column}, ${sort.direction === "desc" ? "high to low" : "low to high"}`;
}

export interface PlayoffOddsSectionProps {
  leagueId: number;
  season: number;
  dataVersion: number;
}

/**
 * The standings page's Playoff odds section: a separately loaded table below the WAPDate standings.
 * Loading, unavailable (per API reason), error, and ready states are all handled here, and the
 * calculation never delays the standings tables or chart.
 */
export function PlayoffOddsSection({ leagueId, season, dataVersion }: PlayoffOddsSectionProps) {
  const { state, reload } = usePlayoffOdds(leagueId, season, dataVersion);
  const [sort, setSort] = useState<SortState>({ key: "playoff", direction: "desc" });

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  return (
    <section aria-labelledby="h-playoff-odds" className="mt-7 md:mt-9">
      <h2 id="h-playoff-odds" className="text-base font-bold">
        Playoff odds
      </h2>

      {state.status === "loading" ? <LoadingState label="Simulating 10,000 seasons…" /> : null}

      {state.status === "error" ? <ErrorState onRetry={reload} message={state.message} /> : null}

      {state.status === "unavailable" ? (
        <EmptyState
          title={PLAYOFF_ODDS_UNAVAILABLE_COPY[state.reason].title}
          detail={PLAYOFF_ODDS_UNAVAILABLE_COPY[state.reason].detail}
        />
      ) : null}

      {state.status === "ready" ? (
        <>
          <p className="mt-1 text-[13px] text-ink-faint">
            {state.odds.iterations === 0
              ? "Regular season complete · final seeding"
              : `${state.odds.iterations.toLocaleString()} simulated seasons · 95% range shown · ${sortLabel(
                  sort,
                )}`}
          </p>
          {state.odds.confidence === "low" && state.odds.iterations > 0 ? (
            <p className="mt-2 rounded-lg border border-warning-line bg-warning-surface px-3 py-2 text-[13px] text-warning-ink">
              Based on {state.odds.completed_weeks} completed{" "}
              {state.odds.completed_weeks === 1 ? "week" : "weeks"}; early-season estimates are
              wide.
            </p>
          ) : null}
          {state.odds.teams.length === 0 ? (
            <EmptyState
              title="No teams to show"
              detail="This season has no stored teams for the playoff simulation."
            />
          ) : (
            <PlayoffOddsTable rows={state.odds.teams} sort={sort} onSort={handleSort} />
          )}
          <details className="mt-3 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink-muted">
            <summary className="cursor-pointer font-semibold">How these are estimated</summary>
            <p className="mt-2">
              Each estimate simulates the remaining regular-season weeks with all four Victory
              Points components, then seeds the final table by Victory Points, head-to-head wins,
              and points for. The 95% range is Monte Carlo uncertainty for this model, not a
              guarantee; early seasons with little history are marked as low confidence.
            </p>
            <p className="mt-2">
              Division winners are seeded first, and byes go to the top division winners allowed by
              the playoff bracket. These are estimates, so a team shown at 100% can still be
              eliminated in a path the model considers vanishingly unlikely.
            </p>
          </details>
        </>
      ) : null}
    </section>
  );
}
