import { useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { PlayoffOddsResponse } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";
import { toggleSort, type SortDirection, type SortState } from "../components/sorting";
import { useLeague } from "./LeagueContext";
import { latestSeason } from "./latestSeason";
import { PLAYOFF_ODDS_UNAVAILABLE_COPY } from "../standings/playoffOddsCopy";
import { PlayoffOddsTable } from "../standings/PlayoffOddsTable";

const MIN_ITERATIONS = 1_000;
const MAX_ITERATIONS = 50_000;
const DEFAULT_ITERATIONS = 10_000;
const MAX_SEED = 2_147_483_647;
const MIN_STRENGTH_WEIGHT = 0;
const MAX_STRENGTH_WEIGHT = 10;
const DEFAULT_STRENGTH_WEIGHT = "1";
const STRENGTH_WEIGHT_PATTERN = /^\d+(?:\.\d+)?$/;

type SimulationState =
  | { status: "idle" }
  | { status: "loading"; iterations: number }
  | { status: "error"; error: DisplayError }
  | { status: "ready"; odds: PlayoffOddsResponse };

function simulationSummary(odds: PlayoffOddsResponse): string {
  if (odds.iterations === 0) {
    return `${odds.season} season · regular season complete · final seeding · strength weight ${odds.strength_weight} · model ${odds.model.version}`;
  }
  return `${odds.season} season · ${odds.iterations.toLocaleString()} simulated seasons · seed ${odds.seed ?? "derived"} · strength weight ${odds.strength_weight} · model ${odds.model.version}`;
}

/**
 * Admin: run the playoff-odds simulation for the current season only.
 *
 * The current season is the league's latest stored season, the same rule the API enforces. There is
 * deliberately no season selector, so a prior season can never be simulated from this page. This
 * section is separate from the seasons table: running it never contacts ESPN, never refreshes stored
 * data, and never changes the shared data version. It reveals the iteration count, optional seed,
 * and team-strength weight, runs the existing member-only odds endpoint, and shows the same table as
 * the standings page. A missing playoff field or an incomplete schedule is reported with the
 * documented unavailable copy, pointing the admin at the Seasons refresh.
 */
export function PlayoffOddsAdminSection({ leagueId }: { leagueId: number }) {
  const { seasons, seasonsStatus, seasonsError, reloadSeasons } = useLeague();
  const currentSeason = latestSeason(seasons);
  const [iterations, setIterations] = useState(String(DEFAULT_ITERATIONS));
  const [seed, setSeed] = useState("");
  const [strengthWeight, setStrengthWeight] = useState(DEFAULT_STRENGTH_WEIGHT);
  const [formError, setFormError] = useState<string | null>(null);
  const [state, setState] = useState<SimulationState>({ status: "idle" });
  const [sort, setSort] = useState<SortState>({ key: "playoff", direction: "desc" });

  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };

  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    if (currentSeason === null) {
      setFormError("The league has no current stored season to simulate.");
      return;
    }
    const iterationText = iterations.trim();
    const parsedIterations = Number(iterationText);
    if (
      iterationText === "" ||
      !Number.isInteger(parsedIterations) ||
      parsedIterations < MIN_ITERATIONS ||
      parsedIterations > MAX_ITERATIONS
    ) {
      setFormError(
        `Enter a whole number of simulations from ${MIN_ITERATIONS.toLocaleString()} to ${MAX_ITERATIONS.toLocaleString()}.`,
      );
      return;
    }
    const weightText = strengthWeight.trim();
    const parsedWeight = Number(weightText);
    if (
      !STRENGTH_WEIGHT_PATTERN.test(weightText) ||
      !Number.isFinite(parsedWeight) ||
      parsedWeight < MIN_STRENGTH_WEIGHT ||
      parsedWeight > MAX_STRENGTH_WEIGHT
    ) {
      setFormError(
        `Enter a team strength weight from ${MIN_STRENGTH_WEIGHT} to ${MAX_STRENGTH_WEIGHT}, for example 1 or 0.5.`,
      );
      return;
    }
    const seedText = seed.trim();
    let parsedSeed: number | undefined;
    if (seedText !== "") {
      parsedSeed = Number(seedText);
      if (!Number.isInteger(parsedSeed) || parsedSeed < 0 || parsedSeed > MAX_SEED) {
        setFormError(
          `Enter a whole seed from 0 to ${MAX_SEED.toLocaleString()}, or leave it blank.`,
        );
        return;
      }
    }

    setState({ status: "loading", iterations: parsedIterations });
    try {
      const odds = await api.playoffOdds(leagueId, currentSeason, {
        iterations: parsedIterations,
        strengthWeight: weightText,
        ...(parsedSeed === undefined ? {} : { seed: parsedSeed }),
      });
      setState({ status: "ready", odds });
      setSort({ key: "playoff", direction: "desc" });
    } catch (failure) {
      setState({ status: "error", error: toDisplayError(failure) });
    }
  };

  return (
    <section aria-labelledby="h-playoff-odds-admin" className="mt-7">
      <h2 id="h-playoff-odds-admin" className="text-base font-bold">
        Playoff odds simulation
      </h2>
      <p className="mt-1 text-[13px] text-ink-faint">
        Run the remaining-season simulation for the current season only, the league&apos;s latest
        stored season. This does not contact ESPN or refresh stored data; use the Seasons table
        above when a season needs a provider re-sync. Prior seasons are not simulated.
      </p>

      {seasonsStatus === "loading" ? <LoadingState label="Loading seasons…" /> : null}

      {seasonsStatus === "error" ? (
        <ErrorState onRetry={reloadSeasons} message={seasonsError ?? undefined} />
      ) : null}

      {seasonsStatus === "ready" && seasons.length === 0 ? (
        <EmptyState
          title="No stored seasons"
          detail="Add a season above before running the playoff simulation."
        />
      ) : null}

      {seasonsStatus === "ready" && seasons.length > 0 ? (
        <form
          className="mt-3 rounded-xl border border-line bg-surface p-4"
          onSubmit={run}
          noValidate
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <span className={labelClass}>Simulation season</span>
              <p className="mt-1 text-sm font-semibold text-ink">
                {currentSeason} — current season
              </p>
            </div>
            <div>
              <label htmlFor="playoff-odds-iterations" className={labelClass}>
                Simulations
              </label>
              <input
                id="playoff-odds-iterations"
                type="number"
                inputMode="numeric"
                min={MIN_ITERATIONS}
                max={MAX_ITERATIONS}
                step={1}
                value={iterations}
                disabled={state.status === "loading"}
                onChange={(event) => setIterations(event.target.value)}
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
                type="number"
                inputMode="decimal"
                min={MIN_STRENGTH_WEIGHT}
                max={MAX_STRENGTH_WEIGHT}
                step={0.1}
                value={strengthWeight}
                disabled={state.status === "loading"}
                onChange={(event) => setStrengthWeight(event.target.value)}
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
                type="number"
                inputMode="numeric"
                min={0}
                max={MAX_SEED}
                step={1}
                value={seed}
                placeholder="Derived from inputs"
                disabled={state.status === "loading"}
                onChange={(event) => setSeed(event.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          <p id="playoff-odds-iterations-hint" className="mt-2 text-[12px] text-ink-faint">
            Use 1,000 to 50,000 simulations; 10,000 is the default. Leave the seed blank to derive a
            stable one from the season data.
          </p>
          <p id="playoff-odds-strength-weight-hint" className="mt-1 text-[12px] text-ink-faint">
            0 makes every remaining matchup even (all teams share one score distribution), 1 is the
            current model, and values above 1 overweight stronger teams; the maximum is 10. Decimals
            are allowed. Only simulated future scores change: the current VP, wins, and points for
            still decide seeding, and no stored data is modified.
          </p>

          {formError === null ? null : (
            <p role="alert" className="mt-2 text-[13px] font-semibold text-danger-ink">
              {formError}
            </p>
          )}

          <button
            type="submit"
            className={`${primaryButtonClass} mt-3`}
            disabled={state.status === "loading"}
          >
            {state.status === "loading"
              ? `Running ${state.iterations.toLocaleString()} simulations…`
              : "Run simulations"}
          </button>
        </form>
      ) : null}

      {state.status === "loading" ? (
        <LoadingState label={`Running ${state.iterations.toLocaleString()} simulated seasons…`} />
      ) : null}

      {state.status === "error" ? <ApiAlert error={state.error} /> : null}

      {state.status === "ready" && state.odds.season === currentSeason ? (
        <SimulationResult odds={state.odds} sort={sort} onSort={handleSort} />
      ) : null}
    </section>
  );
}

function SimulationResult({
  odds,
  sort,
  onSort,
}: {
  odds: PlayoffOddsResponse;
  sort: SortState;
  onSort: (key: string, initialDirection: SortDirection) => void;
}) {
  if (odds.status === "unavailable" && odds.reason !== null) {
    const copy = PLAYOFF_ODDS_UNAVAILABLE_COPY[odds.reason];
    return (
      <div role="status" aria-live="polite" className="mt-3">
        <EmptyState title={copy.title} detail={copy.detail} />
      </div>
    );
  }

  return (
    <div role="status" aria-live="polite" className="mt-3">
      <p className="text-[13px] font-semibold text-ink">{simulationSummary(odds)}</p>
      <p className="mt-1 text-[13px] text-ink-faint">
        {odds.completed_weeks} completed {odds.completed_weeks === 1 ? "week" : "weeks"} ·{" "}
        {odds.remaining_weeks.length} remaining{" "}
        {odds.remaining_weeks.length === 1 ? "week" : "weeks"} · playoff field{" "}
        {odds.playoff_field ?? "unknown"} · {odds.division_count}{" "}
        {odds.division_count === 1 ? "division" : "divisions"}
      </p>
      {odds.confidence === "low" && odds.iterations > 0 ? (
        <p className="mt-2 rounded-lg border border-warning-line bg-warning-surface px-3 py-2 text-[13px] text-warning-ink">
          Low confidence: the season has little completed history, so these estimates are wide.
        </p>
      ) : null}
      {odds.teams.length === 0 ? (
        <EmptyState
          title="No team results"
          detail="The simulation returned no team rows for this season."
        />
      ) : (
        <PlayoffOddsTable rows={odds.teams} sort={sort} onSort={onSort} />
      )}
      <p className="mt-2 text-[12px] text-ink-faint">
        Model {odds.model.version}: {odds.model.shrink_games} shrink games,{" "}
        {odds.model.residual_mix_games} residual-mix games, scores to {odds.model.score_precision},
        points for breaks ties. Intervals are 95% Monte Carlo uncertainty conditional on the model.
      </p>
    </div>
  );
}
