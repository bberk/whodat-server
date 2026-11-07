import { useEffect, useState } from "react";

import { ClinchLegend } from "../components/ClinchBadge";
import { DataState, EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { FinalPlaceLegend } from "../components/FinalPlaceBadge";
import { formatProjectionAsOf } from "../components/format";
import { StandingsTable } from "../components/StandingsTable";
import { VPRulesTooltip } from "../components/VPRulesTooltip";
import { useMediaQuery } from "../components/useMediaQuery";
import { VPChart } from "../components/VPChart";
import { useLeague } from "../leagues/LeagueContext";
import { latestSeason } from "../leagues/latestSeason";
import {
  buildHistorySeries,
  seasonHasHeadToHeadTies,
  seriesIndexByTeamId,
} from "../standings/model";
import { PlayoffOddsSection } from "../standings/PlayoffOddsSection";
import { ProjectedWeekToggle } from "../standings/ProjectedWeekToggle";
import { useStandingsData } from "../standings/useStandingsData";
import { WapdateSection } from "../standings/WapdateSection";

const EMPTY_STYLES: ReadonlyMap<number, number> = new Map<number, number>();

/**
 * The standings dashboard: overall and per-division tables and the cumulative VP chart, each with
 * loading, empty, and error states. Data comes from the API for the league and season selected in
 * the app shell.
 */
export function StandingsPage() {
  const {
    selectedLeague,
    leaguesStatus,
    leaguesError,
    reloadLeagues,
    seasonsStatus,
    seasonsError,
    seasons,
    season,
    dataVersion,
  } = useLeague();
  const [includeProjected, setIncludeProjected] = useState(false);
  const { state, reload } = useStandingsData(
    selectedLeague?.league_id ?? null,
    season,
    dataVersion,
    includeProjected,
  );
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [hiddenTeamIds, setHiddenTeamIds] = useState<ReadonlySet<number>>(() => new Set<number>());
  const compact = useMediaQuery("(max-width: 767px)");

  // Projected reads are current-season only, so switching seasons must not carry the switch over.
  useEffect(() => {
    setIncludeProjected(false);
  }, [season]);

  if (leaguesStatus === "loading") {
    return (
      <div className="pt-5 md:pt-6">
        <LoadingState label="Loading your leagues…" />
      </div>
    );
  }

  if (leaguesStatus === "error") {
    return (
      <div className="pt-5 md:pt-6">
        <ErrorState onRetry={reloadLeagues} message={leaguesError ?? undefined} />
      </div>
    );
  }

  if (selectedLeague === null) {
    return (
      <div className="pt-5 md:pt-6">
        <EmptyState
          title="No leagues yet"
          detail="Add an ESPN league to see its standings. Admins can add a league; members can join with an invite code."
        />
      </div>
    );
  }

  if (seasonsStatus === "loading") {
    return (
      <div className="pt-5 md:pt-6">
        <LoadingState label="Loading seasons…" />
      </div>
    );
  }

  if (seasonsStatus === "error") {
    return (
      <div className="pt-5 md:pt-6">
        <ErrorState onRetry={reloadLeagues} message={seasonsError ?? undefined} />
      </div>
    );
  }

  if (season === null) {
    return (
      <div className="pt-5 md:pt-6">
        <EmptyState
          title="No seasons yet"
          detail="This league has no stored seasons. An admin can add one from the league admin page."
        />
      </div>
    );
  }

  const bundle = state.status === "ready" ? state : null;
  const tableWeeks = bundle === null ? [] : bundle.standings.weeks;
  const chartWeeks = bundle === null ? [] : bundle.history.weeks;
  const projectedWeeks = bundle === null ? [] : bundle.history.projected_weeks;
  const series = bundle === null ? [] : buildHistorySeries(bundle.history);
  const teamStyles = bundle === null ? EMPTY_STYLES : seriesIndexByTeamId(bundle.history);
  const showTies = bundle === null ? false : seasonHasHeadToHeadTies(bundle.standings.overall);
  const currentSeason = latestSeason(seasons);
  const showPlayoffOdds = currentSeason !== null && season === currentSeason;
  const activeWeek = bundle === null ? null : bundle.standings.active_week;
  const projection = bundle === null ? null : bundle.standings.projection;
  const appliedProjectedWeek = projection?.week ?? null;
  const projectionAsOf = projection?.as_of ?? null;
  const projectionUnavailable = includeProjected && projection?.status === "unavailable";
  const projectedPointsByTeam =
    projection?.status === "ok"
      ? new Map(projection.teams.map((team) => [team.team_id, team.points]))
      : undefined;
  const canProject = showPlayoffOdds;
  const projectionReason =
    activeWeek === null
      ? "This season has no active week to project (it is complete, or the schedule is incomplete)."
      : projectionUnavailable
        ? `Projected results are unavailable (${projection?.reason ?? "not synced"}); showing completed weeks.`
        : null;
  const visibleTeamIds = series
    .filter((entry) => !hiddenTeamIds.has(entry.teamId))
    .map((entry) => entry.teamId);

  const selectTeam = (teamId: number) => {
    setSelectedTeamId((current) => (current === teamId ? null : teamId));
    setHiddenTeamIds((current) => {
      if (!current.has(teamId)) {
        return current;
      }
      const next = new Set(current);
      next.delete(teamId);
      return next;
    });
  };

  const toggleSeries = (teamId: number) => {
    setHiddenTeamIds((current) => {
      const next = new Set(current);
      if (next.has(teamId)) {
        next.delete(teamId);
      } else {
        next.add(teamId);
      }
      return next;
    });
  };

  // Double-clicking a legend chip hides every other series and keeps the clicked team visible.
  const isolateSeries = (teamId: number) => {
    setHiddenTeamIds(
      new Set(series.filter((entry) => entry.teamId !== teamId).map((entry) => entry.teamId)),
    );
  };

  const meta =
    bundle === null
      ? `${season} season`
      : `${bundle.standings.season} season · ${bundle.standings.overall.length} teams · ${bundle.standings.divisions.length} divisions · ${bundle.standings.completed_weeks} completed weeks${
          appliedProjectedWeek === null ? "" : ` · projecting week ${appliedProjectedWeek}`
        }`;

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex flex-col gap-1 pt-5 md:pt-6">
        <h1 className="text-xl font-bold md:text-2xl">{selectedLeague.name} — standings</h1>
        <p className="text-[13px] text-ink-faint">{meta}</p>
      </div>

      <section aria-labelledby="h-overall" className="mt-7 md:mt-9">
        <div className="relative flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 id="h-overall" className="text-base font-bold">
            Overall standings
          </h2>
          <VPRulesTooltip />
        </div>
        {canProject ? (
          <>
            <ProjectedWeekToggle
              week={activeWeek}
              checked={includeProjected && !projectionUnavailable}
              disabled={projectionUnavailable}
              reason={projectionReason}
              onChange={setIncludeProjected}
            />
            {appliedProjectedWeek !== null && projectionAsOf !== null ? (
              <p className="mt-1 text-[12px] text-ink-faint">
                ESPN projections as of {formatProjectionAsOf(projectionAsOf)}.
              </p>
            ) : null}
          </>
        ) : null}
        {bundle === null ? (
          <DataState
            state={state}
            loadingLabel="Loading standings…"
            emptyTitle="No completed weeks yet"
            emptyDetail="Standings appear after the first completed week of the season."
            onRetry={reload}
          />
        ) : (
          <>
            <ClinchLegend />
            {bundle.standings.overall.some((row) => row.final_standing !== null) ? (
              <FinalPlaceLegend />
            ) : null}
            <StandingsTable
              caption={`Overall ${bundle.standings.season} standings: rank, team, final placing, playoff designation, owner, season victory points, head-to-head record, points for, and victory points for each counted week.`}
              ariaLabel="Overall standings, scrollable horizontally"
              rows={bundle.standings.overall}
              weeks={tableWeeks}
              projectedWeek={appliedProjectedWeek}
              projectedPointsByTeam={projectedPointsByTeam}
              showTies={showTies}
              selectedTeamId={selectedTeamId}
              onSelectTeam={selectTeam}
              seriesIndexByTeamId={teamStyles}
            />
          </>
        )}
      </section>

      <section aria-labelledby="h-divisions" className="mt-7 md:mt-9">
        <h2 id="h-divisions" className="text-base font-bold">
          Division standings
        </h2>
        {bundle === null ? (
          <DataState
            state={state}
            loadingLabel="Loading division standings…"
            emptyTitle="No completed weeks yet"
            emptyDetail="Division standings appear after the first completed week of the season."
            onRetry={reload}
          />
        ) : bundle.standings.divisions.length === 0 ? (
          <EmptyState
            title="No divisions"
            detail="This league has no divisions; the overall table lists every team."
          />
        ) : (
          <div className="mt-3 grid gap-5 xl:grid-cols-2">
            {bundle.standings.divisions.map((division, index) => {
              const name = division.name ?? `Division ${index + 1}`;
              return (
                <div key={`${division.name ?? "division"}-${index}`} className="min-w-0">
                  <h3 className="text-sm font-semibold text-ink-muted">{name}</h3>
                  <StandingsTable
                    caption={`${name} division standings, ${bundle.standings.season}: rank, team, final placing, owner, season victory points, head-to-head record, and points for. Ranks are overall league ranks; weekly VP columns stay on the overall table.`}
                    ariaLabel={`${name} division standings, scrollable horizontally`}
                    rows={division.standings}
                    weeks={[]}
                    showTies={showTies}
                    selectedTeamId={selectedTeamId}
                    onSelectTeam={selectTeam}
                    seriesIndexByTeamId={teamStyles}
                  />
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section aria-labelledby="h-chart" className="mt-7 md:mt-9">
        <h2 id="h-chart" className="text-base font-bold">
          Cumulative VP by week
        </h2>
        {bundle === null ? (
          <DataState
            state={state}
            loadingLabel="Loading the VP chart…"
            emptyTitle="No chart yet"
            emptyDetail="The cumulative VP chart appears after the first completed week."
            onRetry={reload}
          />
        ) : chartWeeks.length === 0 ? (
          <EmptyState
            title="No chart yet"
            detail="The cumulative VP chart appears after the first completed week."
          />
        ) : (
          <VPChart
            weeks={chartWeeks}
            series={series}
            visibleTeamIds={visibleTeamIds}
            selectedTeamId={selectedTeamId}
            onToggleTeam={toggleSeries}
            onIsolateTeam={isolateSeries}
            compact={compact}
            projectedWeeks={projectedWeeks}
          />
        )}
      </section>

      {/* A hidden WAPDate section is never mounted, so its hook makes no /wapdate request. */}
      {selectedLeague.show_wapdate ? (
        <WapdateSection
          leagueId={selectedLeague.league_id}
          season={season}
          dataVersion={dataVersion}
          includeProjected={includeProjected}
        />
      ) : null}

      {/* Odds estimate the season in progress; a prior stored season is hidden and never requested. */}
      {showPlayoffOdds ? (
        <PlayoffOddsSection
          leagueId={selectedLeague.league_id}
          season={season}
          dataVersion={dataVersion}
          includeProjected={includeProjected}
        />
      ) : null}
    </div>
  );
}
