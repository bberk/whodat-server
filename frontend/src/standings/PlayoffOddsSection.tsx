import { useState, type FormEvent } from "react";

import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";
import { toggleSort, type SortDirection, type SortState } from "../components/sorting";
import { PLAYOFF_ODDS_UNAVAILABLE_COPY } from "./playoffOddsCopy";
import {
  DEFAULT_ITERATIONS,
  DEFAULT_STRENGTH_WEIGHT,
  MAX_SEED,
  MAX_STRENGTH_WEIGHT,
  MIN_ITERATIONS,
  MIN_STRENGTH_WEIGHT,
  maxIterationsForRole,
  parseControls,
  type PlayoffOddsRequest,
} from "./playoffOddsControls";
import { PlayoffOddsTable } from "./PlayoffOddsTable";
import { usePlayoffOdds } from "./usePlayoffOdds";

function sortLabel(sort: SortState): string {
  const column =
    sort.key === "bye" ? "Bye %" : sort.key === "championship" ? "Championship %" : "Playoff %";
  return `sorted by ${column}, ${sort.direction === "desc" ? "high to low" : "low to high"}`;
}

export interface PlayoffOddsSectionProps {
  leagueId: number;
  season: number;
  dataVersion: number;
}

/**
 * The standings page's Playoff odds section: a separately loaded table below the WAPDate standings,
 * with the simulation controls that used to live on the admin page.
 *
 * The current iteration cap depends on the authenticated role: regular members may request up to
 * 10,000 seasons and admins up to 100,000. The weight and seed are parsed explicitly, so ".25" and
 * "1." are accepted without a leading zero or a number-input step. Loading, unavailable (per API
 * reason), error, and ready states are all handled here, and the calculation never delays the
 * standings tables or chart.
 */
export function PlayoffOddsSection({ leagueId, season, dataVersion }: PlayoffOddsSectionProps) {
  const { user } = useAuth();
  const maxIterations = maxIterationsForRole(user?.role);
  const [iterationsText, setIterationsText] = useState(String(DEFAULT_ITERATIONS));
  const [strengthWeightText, setStrengthWeightText] = useState(DEFAULT_STRENGTH_WEIGHT);
  const [seedText, setSeedText] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [request, setRequest] = useState<PlayoffOddsRequest>(() => ({
    iterations: DEFAULT_ITERATIONS,
    strengthWeight: DEFAULT_STRENGTH_WEIGHT,
  }));
  const [runId, setRunId] = useState(0);
  const [sort, setSort] = useState<SortState>({ key: "playoff", direction: "desc" });
  const { state, reload } = usePlayoffOdds(leagueId, season, dataVersion, request, runId);

  const busy = state.status === "loading";
  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  const run = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = parseControls(
      { iterations: iterationsText, strengthWeight: strengthWeightText, seed: seedText },
      maxIterations,
    );
    if (!parsed.ok) {
      setFormError(parsed.message);
      return;
    }
    setFormError(null);
    setRequest(parsed.request);
    setRunId((current) => current + 1);
  };

  return (
    <section aria-labelledby="h-playoff-odds" className="mt-7 md:mt-9">
      <h2 id="h-playoff-odds" className="text-base font-bold">
        Playoff odds
      </h2>

      <form className="mt-3 rounded-xl border border-line bg-surface p-4" onSubmit={run} noValidate>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <label htmlFor="playoff-odds-iterations" className={labelClass}>
              Simulations
            </label>
            <input
              id="playoff-odds-iterations"
              type="text"
              inputMode="numeric"
              value={iterationsText}
              disabled={busy}
              onChange={(event) => setIterationsText(event.target.value)}
              className={inputClass}
              aria-describedby="playoff-odds-iterations-hint"
            />
          </div>
          <div>
            <label htmlFor="playoff-odds-strength-weight" className={labelClass}>
              Team strength weight
            </label>
            <input
              id="playoff-odds-strength-weight"
              type="text"
              inputMode="decimal"
              value={strengthWeightText}
              disabled={busy}
              onChange={(event) => setStrengthWeightText(event.target.value)}
              className={inputClass}
              aria-describedby="playoff-odds-strength-weight-hint"
            />
          </div>
          <div>
            <label htmlFor="playoff-odds-seed" className={labelClass}>
              Seed (optional)
            </label>
            <input
              id="playoff-odds-seed"
              type="text"
              inputMode="numeric"
              value={seedText}
              placeholder="Derived from inputs"
              disabled={busy}
              onChange={(event) => setSeedText(event.target.value)}
              className={inputClass}
              aria-describedby="playoff-odds-seed-hint"
            />
          </div>
          <div className="flex items-end">
            <button type="submit" className={primaryButtonClass} disabled={busy}>
              {busy ? `Running ${request.iterations.toLocaleString()} simulations…` : "Run"}
            </button>
          </div>
        </div>

        <p id="playoff-odds-iterations-hint" className="mt-2 text-[12px] text-ink-faint">
          Use {MIN_ITERATIONS.toLocaleString()} to {maxIterations.toLocaleString()} simulations;{" "}
          {DEFAULT_ITERATIONS.toLocaleString()} is the default.
        </p>
        <p id="playoff-odds-strength-weight-hint" className="mt-1 text-[12px] text-ink-faint">
          {MIN_STRENGTH_WEIGHT} makes every remaining matchup even (all teams share one score
          distribution), 1 is the current model, and values above 1 overweight stronger teams; the
          maximum is {MAX_STRENGTH_WEIGHT}. Any numeric form works, such as .25 or 1. Only simulated
          future scores change: current VP, wins, and points for still decide seeding.
        </p>
        <p id="playoff-odds-seed-hint" className="mt-1 text-[12px] text-ink-faint">
          Leave the seed blank to derive a stable one from the season data, or enter a whole number
          from 0 to {MAX_SEED.toLocaleString()} to reproduce a run.
        </p>

        {formError === null ? null : (
          <p role="alert" className="mt-2 text-[13px] font-semibold text-danger-ink">
            {formError}
          </p>
        )}
      </form>

      {state.status === "loading" ? (
        <LoadingState label={`Simulating ${request.iterations.toLocaleString()} seasons…`} />
      ) : null}

      {state.status === "error" ? <ErrorState onRetry={reload} message={state.message} /> : null}

      {state.status === "unavailable" ? (
        <EmptyState
          title={PLAYOFF_ODDS_UNAVAILABLE_COPY[state.reason].title}
          detail={PLAYOFF_ODDS_UNAVAILABLE_COPY[state.reason].detail}
        />
      ) : null}

      {state.status === "ready" ? (
        <>
          <p className="mt-3 text-[13px] text-ink-faint">
            {state.odds.remaining_weeks.length === 0
              ? "Regular season complete · projected bracket · "
              : ""}
            {state.odds.iterations.toLocaleString()} simulated seasons · 95% range shown ·{" "}
            {sortLabel(sort)}
          </p>
          {state.odds.confidence === "low" ? (
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
              Points components, seeds the final table by Victory Points, head-to-head wins, and
              points for, then projects a reseeded playoff bracket. The highest remaining seed plays
              the lowest, byes apply only in the first round, every round draws fresh scores, and an
              exact tie goes to the higher seed. The 95% range is Monte Carlo uncertainty for this
              model, not a guarantee; early seasons with little history are marked as low
              confidence.
            </p>
            <p className="mt-2">
              Real stored playoff matchups are not used: the bracket is a projection. These are
              estimates, so a team shown at 100% can still be eliminated in a path the model
              considers vanishingly unlikely.
            </p>
          </details>
        </>
      ) : null}
    </section>
  );
}
