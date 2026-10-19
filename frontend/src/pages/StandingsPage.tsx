import { useState } from "react";

import { DataState } from "../components/DataStates";
import { StandingsTable } from "../components/StandingsTable";
import { VPRulesTooltip } from "../components/VPRulesTooltip";
import { useMediaQuery } from "../components/useMediaQuery";
import { useStandingsData } from "../components/useStandingsData";
import { WeeklyVPBreakdown } from "../components/WeeklyVPBreakdown";
import { VPChart } from "../components/VPChart";
import {
  buildHistorySeries,
  defaultStandingsSource,
  seasonHasHeadToHeadTies,
  seriesIndexByTeamId,
  weeklyBreakdownFor,
  type StandingsSource,
} from "../mocks/standings";

export interface StandingsPageProps {
  /** Data source; defaults to the isolated mock and is swapped for the real client once M4 lands. */
  source?: StandingsSource;
}

const DEFAULT_SEASON = 2026;
const EMPTY_STYLES: ReadonlyMap<number, number> = new Map<number, number>();

const selectClass =
  "min-w-[96px] rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-sm text-gray-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:bg-gray-50 disabled:text-gray-400";

/**
 * The standings dashboard: overall and per-division tables, the cumulative VP chart, and the
 * weekly VP component breakdown, each with loading, empty, and error states. Data comes from an
 * injected source (the isolated mock by default) so the real API client can replace it later.
 */
export function StandingsPage({ source = defaultStandingsSource }: StandingsPageProps) {
  const { state, reload } = useStandingsData(source);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [hiddenTeamIds, setHiddenTeamIds] = useState<ReadonlySet<number>>(() => new Set<number>());
  const [season, setSeason] = useState(DEFAULT_SEASON);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);
  const compact = useMediaQuery("(max-width: 767px)");

  const bundle = state.status === "ready" ? state.bundle : null;
  const weeks = bundle === null ? [] : bundle.history.weeks;
  const series = bundle === null ? [] : buildHistorySeries(bundle);
  const teamStyles = bundle === null ? EMPTY_STYLES : seriesIndexByTeamId(bundle);
  const showTies = bundle === null ? false : seasonHasHeadToHeadTies(bundle.standings.overall);
  const visibleTeamIds = series
    .filter((entry) => !hiddenTeamIds.has(entry.teamId))
    .map((entry) => entry.teamId);
  const activeWeek = selectedWeek ?? weeks[weeks.length - 1];
  const weekly = bundle === null ? null : weeklyBreakdownFor(bundle, activeWeek);

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

  const meta =
    bundle === null
      ? `${season} season`
      : `${season} season · ${bundle.standings.overall.length} teams · ${bundle.standings.divisions.length} divisions · ${bundle.standings.completed_weeks} completed weeks`;

  return (
    <div className="flex min-h-full flex-col bg-gray-50 text-gray-900">
      <div role="note" className="border-b border-amber-300 bg-amber-50 text-[13px] text-amber-800">
        <div className="mx-auto max-w-[1200px] px-4 py-2 md:px-6">
          <strong className="font-bold">Illustrative data.</strong> This screen reads an isolated
          mock source, not ESPN or a live league. Numbers are fixture data derived from
          ACCEPTANCE.md §1.1 worked examples.
        </div>
      </div>

      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-[1200px] items-center gap-3 px-4 py-3 md:px-6">
          <span
            aria-hidden="true"
            className="flex h-[34px] w-[34px] items-center justify-center rounded-lg bg-brand text-[15px] font-bold tracking-wide text-brand-foreground"
          >
            VP
          </span>
          <div>
            <p className="text-[15px] font-semibold">Victory Points Standings</p>
            <p className="text-xs text-gray-500">Example League</p>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-[13px] text-gray-700">
            <span
              aria-hidden="true"
              className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-brand bg-brand-foreground text-xs font-bold text-brand"
            >
              A
            </span>
            <span className="hidden md:inline">Alex (Alpha)</span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full min-w-0 max-w-[1200px] flex-1 px-4 pb-10 md:px-6">
        <div className="flex flex-col gap-3 pt-5 md:flex-row md:items-end md:justify-between md:pt-6">
          <div>
            <h1 className="text-xl font-bold md:text-2xl">Example League — standings</h1>
            <p className="mt-1 text-[13px] text-gray-500">{meta}</p>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="season" className="text-[13px] font-semibold text-gray-700">
              Season
            </label>
            <select
              id="season"
              value={season}
              onChange={(event) => setSeason(Number(event.target.value))}
              className={selectClass}
            >
              <option value={2026}>2026</option>
              <option value={2025} disabled>
                2025 (no data)
              </option>
              <option value={2024} disabled>
                2024 (no data)
              </option>
            </select>
          </div>
        </div>

        <section aria-labelledby="h-overall" className="mt-7 md:mt-9">
          <div className="relative flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 id="h-overall" className="text-base font-bold">
              Overall standings
            </h2>
            <VPRulesTooltip />
          </div>
          <p className="mt-1 text-[13px] text-gray-500">
            Select a team to highlight its row and its chart line.
          </p>
          {bundle === null ? (
            <DataState
              state={state}
              loadingLabel="Loading standings…"
              emptyTitle="No completed weeks yet"
              emptyDetail="Standings appear after the first completed week of the season."
              onRetry={reload}
            />
          ) : (
            <StandingsTable
              caption={`Overall ${season} standings: rank, team, owner, season victory points, head-to-head record, points for, and victory points for each completed week.`}
              ariaLabel="Overall standings, scrollable horizontally"
              rows={bundle.standings.overall}
              weeks={weeks}
              showTies={showTies}
              selectedTeamId={selectedTeamId}
              onSelectTeam={selectTeam}
              seriesIndexByTeamId={teamStyles}
            />
          )}
        </section>

        <section aria-labelledby="h-divisions" className="mt-7 md:mt-9">
          <h2 id="h-divisions" className="text-base font-bold">
            Division standings
          </h2>
          <p className="mt-1 text-[13px] text-gray-500">
            Same ranking rules, applied within each division; ranks come from the API rows as-is.
          </p>
          {bundle === null ? (
            <DataState
              state={state}
              loadingLabel="Loading division standings…"
              emptyTitle="No completed weeks yet"
              emptyDetail="Division standings appear after the first completed week of the season."
              onRetry={reload}
            />
          ) : (
            <div className="mt-3 grid gap-5 xl:grid-cols-2">
              {bundle.standings.divisions.map((division) => (
                <div key={division.name} className="min-w-0">
                  <h3 className="text-sm font-semibold text-gray-700">{division.name}</h3>
                  <StandingsTable
                    caption={`${division.name} division standings, ${season}.`}
                    ariaLabel={`${division.name} division standings, scrollable horizontally`}
                    rows={division.standings}
                    weeks={weeks}
                    showTies={showTies}
                    selectedTeamId={selectedTeamId}
                    onSelectTeam={selectTeam}
                    seriesIndexByTeamId={teamStyles}
                  />
                </div>
              ))}
            </div>
          )}
        </section>

        <section aria-labelledby="h-chart" className="mt-7 md:mt-9">
          <h2 id="h-chart" className="text-base font-bold">
            Cumulative VP by week
          </h2>
          <p className="mt-1 text-[13px] text-gray-500">
            One line per team. Series differ by color, dash pattern, and marker shape; legend chips
            toggle a series, and the selected team is drawn thicker.
          </p>
          {bundle === null ? (
            <DataState
              state={state}
              loadingLabel="Loading the VP chart…"
              emptyTitle="No chart yet"
              emptyDetail="The cumulative VP chart appears after the first completed week."
              onRetry={reload}
            />
          ) : (
            <VPChart
              weeks={weeks}
              series={series}
              visibleTeamIds={visibleTeamIds}
              selectedTeamId={selectedTeamId}
              onToggleTeam={toggleSeries}
              compact={compact}
            />
          )}
        </section>

        <section aria-labelledby="h-weekly" className="mt-7 md:mt-9">
          <h2 id="h-weekly" className="text-base font-bold">
            Weekly VP breakdown
          </h2>
          <p className="mt-1 text-[13px] text-gray-500">
            Per-week VP components — why each team earned what it earned.
          </p>
          {weekly === null ? (
            <DataState
              state={state}
              loadingLabel="Loading weekly VP…"
              emptyTitle="No weekly VP yet"
              emptyDetail="Weekly components appear after the first completed week."
              onRetry={reload}
            />
          ) : (
            <WeeklyVPBreakdown
              weeks={weeks}
              selectedWeek={activeWeek}
              onSelectWeek={setSelectedWeek}
              rows={weekly.rows}
              note={weekly.note}
              selectedTeamId={selectedTeamId}
            />
          )}
        </section>

        <footer className="mt-8">
          <div className="rounded-xl border border-gray-200 bg-white p-4 text-[12.5px] text-gray-500">
            <p>
              <strong className="font-semibold text-gray-700">Mock data provenance.</strong> All
              numbers are illustrative fixture data derived from ACCEPTANCE.md §1.1 worked examples
              — week 1 = example A (tied high score, 2.5 VP), week 2 = example B with the
              head-to-head tie removed, week 3 = example C (tied low score, -0.5 each), week 4 =
              example D (three-way tie for the high score, 1/3 each). Weekly VP sums conserve to 6,
              and season totals are exact fraction sums displayed at up to 2 decimals. This season
              has no H2H ties, so records show W-L only.
            </p>
            <p className="mt-1.5">
              Team names (Alpha–Foxtrot) and owner names are fictional. Nothing here is synced from
              or represents live ESPN data; the standings API does not exist yet, so the UI reads an
              isolated mock that mirrors the ARCHITECTURE.md §8 response shape. The chart is
              dependency-free inline SVG (SPEC.md §7 suggests Recharts) and the layout is
              mobile-first.
            </p>
          </div>
        </footer>
      </main>
    </div>
  );
}
