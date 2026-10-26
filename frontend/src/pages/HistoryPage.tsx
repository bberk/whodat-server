import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { EloChart } from "../components/EloChart";
import { EloRatingsTable } from "../components/EloRatingsTable";
import { InfoTooltip } from "../components/InfoTooltip";
import { selectClass } from "../components/formStyles";
import { useMediaQuery } from "../components/useMediaQuery";
import { formatEloValue } from "../components/format";
import {
  ALL_ELO_WINDOW,
  LAST_WEEKS_PRESET,
  MODE_DESCRIPTIONS,
  MODE_LABELS,
  buildEloSeries,
  currentSeasonWindow,
  eloWeekKey,
  filterEloHistoryWindow,
  lastWeeksWindow,
  normalizeEloRange,
  resolveEloWindow,
  type EloMode,
  type EloWindow,
} from "../history/model";
import { useEloHistory } from "../history/useEloHistory";
import { useLeague } from "../leagues/LeagueContext";

type WindowPreset = "all" | "season" | "recent" | "custom";

interface WindowChoice {
  preset: WindowPreset;
  window: EloWindow;
}

const filterButtonClass = (active: boolean) =>
  `rounded-lg px-2.5 py-1 text-[12.5px] font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink ${
    active ? "bg-brand text-brand-foreground" : "bg-surface text-ink-subtle hover:text-brand-ink"
  }`;

/**
 * League History page: one running Elo score per franchise across every stored season.
 *
 * The page is member-only through the route guard and the API. It defaults to round robin, offers
 * an explicit mode switch and season filter, and shares one loading/empty/error state between the
 * chart and the current-scores table. History is derived from stored results on every read, so
 * saving settings on the admin page simply invalidates this view (`dataVersion`).
 */
export function HistoryPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague, dataVersion } = useLeague();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<EloMode>("round_robin");
  const [windowChoice, setWindowChoice] = useState<WindowChoice>({
    preset: "all",
    window: ALL_ELO_WINDOW,
  });
  const [selectedTeamKey, setSelectedTeamKey] = useState<string | null>(null);
  const [hiddenTeamKeys, setHiddenTeamKeys] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  const compact = useMediaQuery("(max-width: 767px)");

  useEffect(() => {
    if (validId && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, leagueId, selectedLeague?.league_id, selectLeague]);

  const { state, reload } = useEloHistory(validId ? leagueId : null, mode, dataVersion);

  if (!validId) {
    return <Navigate to="/" replace />;
  }

  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);
  const leagueName = membership?.name ?? `League ${leagueId}`;

  const selectTeam = (teamKey: string) => {
    setSelectedTeamKey((current) => (current === teamKey ? null : teamKey));
    setHiddenTeamKeys((current) => {
      if (!current.has(teamKey)) {
        return current;
      }
      const next = new Set(current);
      next.delete(teamKey);
      return next;
    });
  };

  const toggleTeam = (teamKey: string) => {
    setHiddenTeamKeys((current) => {
      const next = new Set(current);
      if (next.has(teamKey)) {
        next.delete(teamKey);
      } else {
        next.add(teamKey);
      }
      return next;
    });
  };

  const ready = state.status === "ready" ? state.history : null;
  const filtered = ready === null ? null : filterEloHistoryWindow(ready, windowChoice.window);
  const resolved = ready === null ? null : resolveEloWindow(ready.weeks, windowChoice.window);
  const windowStartKey = resolved?.startKey ?? "";
  const windowEndKey = resolved?.endKey ?? "";

  const choosePreset = (preset: Exclude<WindowPreset, "custom">) => {
    if (ready === null) {
      return;
    }
    const next =
      preset === "all"
        ? ALL_ELO_WINDOW
        : preset === "season"
          ? currentSeasonWindow(ready)
          : lastWeeksWindow();
    setWindowChoice({ preset, window: next });
  };

  const chooseRange = (startKey: string, endKey: string) => {
    if (ready === null) {
      return;
    }
    const normalized = normalizeEloRange(ready.weeks, startKey, endKey);
    setWindowChoice({ preset: "custom", window: { kind: "range", ...normalized } });
  };

  // Double-clicking a legend chip shows only that franchise.
  const isolateTeam = (teamKey: string) => {
    if (ready === null) {
      return;
    }
    setHiddenTeamKeys(
      new Set(ready.teams.map((team) => team.team_key).filter((key) => key !== teamKey)),
    );
  };

  const meta =
    ready === null
      ? `${MODE_LABELS[mode]} · all stored history`
      : `${MODE_LABELS[mode]} · ${ready.seasons.length} season${
          ready.seasons.length === 1 ? "" : "s"
        } · ${ready.weeks.length} weeks · ${ready.teams.length} teams`;

  return (
    <div className="flex min-h-full min-w-0 flex-col">
      <div className="flex flex-col gap-1 pt-5 md:pt-6">
        <h1 className="text-xl font-bold md:text-2xl">{leagueName} — history</h1>
        <p className="text-[13px] text-ink-faint">{meta}</p>
      </div>

      <section aria-labelledby="h-elo-model" className="mt-5">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 id="h-elo-model" className="text-base font-bold">
            Elo model
          </h2>
          <InfoTooltip
            id="elo-model-tip"
            label="About the Elo models"
            text="Actual schedule uses only stored head-to-head matchups and skips cup weeks. Round robin compares every team with every other team each completed week, averages each team's pairwise change, and includes cup weeks. Playoffs are excluded in both."
          />
        </div>
        <div
          role="group"
          aria-label="Elo model"
          className="mt-2 inline-flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1"
        >
          <button
            type="button"
            aria-pressed={mode === "round_robin"}
            onClick={() => setMode("round_robin")}
            className={filterButtonClass(mode === "round_robin")}
          >
            Round robin
          </button>
          <button
            type="button"
            aria-pressed={mode === "actual_schedule"}
            onClick={() => setMode("actual_schedule")}
            className={filterButtonClass(mode === "actual_schedule")}
          >
            Actual schedule
          </button>
        </div>
        <p className="mt-2 max-w-3xl text-[13px] text-ink-subtle">{MODE_DESCRIPTIONS[mode]}</p>
        <details className="mt-2 rounded-lg border border-line bg-surface">
          <summary className="cursor-pointer px-3 py-2 text-[13px] font-semibold text-brand-ink">
            How the Elo score works
          </summary>
          <div className="space-y-1 px-3 pb-3 text-[12.5px] text-ink-subtle">
            <p>
              Expected score: <code>E = 1 / (1 + 10^((R_b − R_a) / 400))</code>. Update:{" "}
              <code>R' = R + K × m × (S − E)</code>, where S is 1 for a win, 0.5 for a tie and 0 for
              a loss.
            </p>
            <p>
              The margin multiplier is <code>m = 1 + weight × min(|margin|, cap) / cap</code>. A cup
              week is skipped in actual schedule and rated in round robin.
            </p>
            <p>
              Before each new stored season, ratings regress toward the starting rating. Adding or
              deleting a season recalculates the whole history from stored results.
            </p>
          </div>
        </details>

        {ready === null ? null : (
          <div className="mt-3 flex flex-wrap gap-2 text-[12px] text-ink-muted">
            <span className="rounded-full border border-brand-soft-line bg-brand-soft px-2.5 py-1">
              <strong>{formatEloValue(ready.config.starting_rating)}</strong> start
            </span>
            <span className="rounded-full border border-brand-soft-line bg-brand-soft px-2.5 py-1">
              <strong>K {formatEloValue(ready.config.k_factor)}</strong> per update
            </span>
            <span className="rounded-full border border-brand-soft-line bg-brand-soft px-2.5 py-1">
              <strong>+{Math.round(Number(ready.config.margin_weight) * 100)}%</strong> max margin
              bonus · cap {formatEloValue(ready.config.margin_cap)}
            </span>
            <span className="rounded-full border border-brand-soft-line bg-brand-soft px-2.5 py-1">
              <strong>{Math.round(Number(ready.config.season_regression) * 100)}%</strong> season
              reset
            </span>
          </div>
        )}
      </section>

      {state.status === "loading" ? (
        <div className="mt-4">
          <LoadingState label="Loading Elo history…" />
        </div>
      ) : null}

      {state.status === "error" ? (
        <div className="mt-4">
          <ErrorState onRetry={reload} message={state.message} />
        </div>
      ) : null}

      {state.status === "empty" ? (
        <div className="mt-4">
          <EmptyState
            title="No rated weeks yet"
            detail="Elo appears after the first completed regular-season week with at least two teams and scores. Cup weeks and byes do not rate in actual schedule; cup weeks do rate in round robin."
          />
        </div>
      ) : null}

      {ready === null ? null : (
        <>
          <section aria-labelledby="h-elo-chart" className="mt-7 md:mt-9">
            <h2 id="h-elo-chart" className="text-base font-bold">
              Elo score history
            </h2>
            <p className="mt-1 text-[13px] text-ink-faint">
              {MODE_LABELS[mode]} · one line per franchise · dashed vertical rules mark season
              resets
              {filtered === null
                ? ""
                : ` · ${filtered.weeks.length} of ${ready.weeks.length} weeks shown`}
            </p>

            <div className="mt-3 rounded-xl border border-line bg-surface p-3">
              <div role="group" aria-label="Quick time range" className="flex flex-wrap gap-1">
                <button
                  type="button"
                  aria-pressed={windowChoice.preset === "all"}
                  onClick={() => choosePreset("all")}
                  className={filterButtonClass(windowChoice.preset === "all")}
                >
                  All history
                </button>
                <button
                  type="button"
                  aria-pressed={windowChoice.preset === "season"}
                  onClick={() => choosePreset("season")}
                  className={filterButtonClass(windowChoice.preset === "season")}
                >
                  Current season
                </button>
                <button
                  type="button"
                  aria-pressed={windowChoice.preset === "recent"}
                  onClick={() => choosePreset("recent")}
                  className={filterButtonClass(windowChoice.preset === "recent")}
                >
                  Last {LAST_WEEKS_PRESET} weeks
                </button>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <label
                    htmlFor="elo-window-from"
                    className="block text-[12.5px] font-semibold text-ink-muted"
                  >
                    From week
                  </label>
                  <select
                    id="elo-window-from"
                    className={`${selectClass} mt-1 w-full`}
                    value={windowStartKey}
                    aria-describedby="elo-window-hint"
                    onChange={(event) =>
                      chooseRange(event.target.value, windowEndKey || event.target.value)
                    }
                  >
                    {windowStartKey === "" ? <option value="">No weeks</option> : null}
                    {ready.weeks.map((week) => (
                      <option key={eloWeekKey(week)} value={eloWeekKey(week)}>
                        {week.season} W{week.week}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label
                    htmlFor="elo-window-to"
                    className="block text-[12.5px] font-semibold text-ink-muted"
                  >
                    To week
                  </label>
                  <select
                    id="elo-window-to"
                    className={`${selectClass} mt-1 w-full`}
                    value={windowEndKey}
                    aria-describedby="elo-window-hint"
                    onChange={(event) =>
                      chooseRange(windowStartKey || event.target.value, event.target.value)
                    }
                  >
                    {windowEndKey === "" ? <option value="">No weeks</option> : null}
                    {ready.weeks.map((week) => (
                      <option key={eloWeekKey(week)} value={eloWeekKey(week)}>
                        {week.season} W{week.week}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <p id="elo-window-hint" className="mt-2 text-[12.5px] text-ink-faint">
                {filtered === null || filtered.weeks.length === 0
                  ? "No rated weeks in this range."
                  : `Showing ${filtered.weeks[0].season} W${filtered.weeks[0].week} to ${
                      filtered.weeks[filtered.weeks.length - 1].season
                    } W${filtered.weeks[filtered.weeks.length - 1].week}.`}{" "}
                The current scores table below always lists every team.
              </p>
            </div>

            {filtered === null ? null : filtered.weeks.length === 0 ? (
              <EmptyState
                title="No rated weeks in this range"
                detail="Choose All history, another range, or a season with rated weeks."
              />
            ) : (
              <EloChart
                weeks={filtered.weeks}
                series={buildEloSeries({
                  ...ready,
                  teams: filtered.teams,
                })}
                boundaries={filtered.boundaries}
                mode={mode}
                startingRating={ready.config.starting_rating}
                visibleTeamKeys={filtered.teams
                  .map((team) => team.team_key)
                  .filter((key) => !hiddenTeamKeys.has(key))}
                selectedTeamKey={selectedTeamKey}
                onToggleTeam={toggleTeam}
                onIsolateTeam={isolateTeam}
                onSelectTeam={selectTeam}
                compact={compact}
              />
            )}
          </section>

          <section aria-labelledby="h-elo-current" className="mt-7 md:mt-9">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 id="h-elo-current" className="text-base font-bold">
                  Current scores
                </h2>
                <p className="mt-1 text-[13px] text-ink-faint">
                  Sorted by current Elo · change this week and this season shown to two decimals
                </p>
              </div>
              <span className="rounded-full bg-surface-strong px-2.5 py-1 text-[12px] font-semibold text-ink-muted">
                {MODE_LABELS[mode]}
              </span>
            </div>
            <EloRatingsTable
              teams={ready.teams}
              selectedTeamKey={selectedTeamKey}
              onSelectTeam={selectTeam}
            />

            {ready.unrated_teams.length === 0 ? null : (
              <p className="mt-2 text-[12.5px] text-ink-subtle">
                {ready.unrated_teams.length} team
                {ready.unrated_teams.length === 1 ? "" : "s"} have no rated matchups yet:{" "}
                {ready.unrated_teams.map((team) => team.name).join(", ")}.
              </p>
            )}

            {ready.warnings.length === 0 ? null : (
              <div className="mt-2 text-[12.5px] text-warning-ink">
                <p className="font-semibold">Some stored data was skipped:</p>
                <ul className="list-disc pl-5">
                  {ready.warnings.map((warning) => (
                    <li key={`${warning.season}-${warning.code}-${warning.message}`}>
                      {warning.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="mt-3 text-[12.5px] text-ink-faint">
              Ratings follow the franchise slot, not the owner. A renamed team keeps its history and
              is shown with its latest name. History is recalculated whenever seasons change.{" "}
              {user?.role === "admin" ? (
                <button
                  type="button"
                  onClick={() => navigate(`/leagues/${leagueId}/admin`)}
                  className="font-semibold text-brand-ink underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink"
                >
                  League admin can change the Elo settings.
                </button>
              ) : null}
            </p>
          </section>
        </>
      )}
    </div>
  );
}
