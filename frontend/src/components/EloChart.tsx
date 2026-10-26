import type { EloWeek } from "../api/types";
import { niceIntegerScale, positionFor, selectWeekLabelIndices } from "./chartGeometry";
import { formatEloValue, formatEloWhole } from "./format";
import { seriesStyle } from "./series";
import { BODY_CELL_DIVIDER, LAST_ROW_NO_DIVIDER } from "./tableStyles";

export interface EloChartSeries {
  teamKey: string;
  name: string;
  ownerName: string | null;
  styleIndex: number;
  /** One value per `weeks` entry; `null` means the team was not in that season. */
  values: (string | null)[];
  current: string;
}

export interface EloChartProps {
  weeks: EloWeek[];
  series: EloChartSeries[];
  boundaries: { season: number; week_index: number }[];
  mode: "actual_schedule" | "round_robin";
  startingRating: string;
  visibleTeamKeys: readonly string[];
  selectedTeamKey: string | null;
  onToggleTeam: (teamKey: string) => void;
  /** Hide every series except this team (legend double-click). */
  onIsolateTeam: (teamKey: string) => void;
  onSelectTeam: (teamKey: string) => void;
  compact: boolean;
}

const LAYOUT = {
  compact: { width: 360, height: 310, top: 38, right: 12, bottom: 30, left: 42 },
  full: { width: 760, height: 420, top: 44, right: 16, bottom: 44, left: 52 },
} as const;

const MODE_LABELS = {
  actual_schedule: "Actual schedule",
  round_robin: "Round robin",
} as const;

interface Point {
  x: number;
  y: number;
}

/** Split a series into contiguous non-null segments so gaps are not bridged by a line. */
function segmentsFor(
  values: readonly (string | null)[],
  xFor: (index: number) => number,
  yFor: (value: number) => number,
): Point[][] {
  const segments: Point[][] = [];
  let current: Point[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length > 0) {
        segments.push(current);
        current = [];
      }
      return;
    }
    current.push({ x: xFor(index), y: yFor(Number(value)) });
  });
  if (current.length > 0) {
    segments.push(current);
  }
  return segments;
}

function lastValue(series: EloChartSeries): string | null {
  for (let index = series.values.length - 1; index >= 0; index -= 1) {
    const value = series.values[index];
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function summaryFor(
  weeks: readonly EloWeek[],
  series: readonly EloChartSeries[],
  visible: ReadonlySet<string>,
  mode: EloChartProps["mode"],
): string {
  const first = weeks[0];
  const last = weeks[weeks.length - 1];
  const ranked = series
    .filter((entry) => visible.has(entry.teamKey))
    .map((entry) => ({ entry, value: lastValue(entry) }))
    .filter((item): item is { entry: EloChartSeries; value: string } => item.value !== null)
    .sort((left, right) => Number(right.value) - Number(left.value));
  const leader =
    ranked.length === 0
      ? "No visible team has a rating yet."
      : `${ranked[0].entry.name} leads at ${formatEloValue(ranked[0].value)}.`;
  return `Elo score history, ${MODE_LABELS[mode]}, ${weeks.length} chart weeks from ${first.season} week ${first.week} to ${last.season} week ${last.week}. ${leader} Ratings regress toward the starting rating before each new season.`;
}

/**
 * Running Elo chart drawn as dependency-free inline SVG.
 *
 * Season starts get vertical rules and season labels (thinned when the axis is narrow), and
 * non-null values are joined in segments so a franchise that missed a season has a real gap. Every
 * rated week is a plain dot; series differ by color, dash pattern, and line weight, the selected
 * team is drawn last and thicker, and legend buttons toggle visibility or select a team. The
 * `<details>` table is the chart's non-visual equivalent and includes every exact value.
 */
export function EloChart({
  weeks,
  series,
  boundaries,
  mode,
  startingRating,
  visibleTeamKeys,
  selectedTeamKey,
  onToggleTeam,
  onIsolateTeam,
  onSelectTeam,
  compact,
}: EloChartProps) {
  const layout = compact ? LAYOUT.compact : LAYOUT.full;
  const plotWidth = layout.width - layout.left - layout.right;
  const plotHeight = layout.height - layout.top - layout.bottom;
  const visible = new Set(visibleTeamKeys);

  if (weeks.length === 0 || series.length === 0) {
    return (
      <div className="mt-3 rounded-xl border border-line bg-surface p-6 text-center text-sm text-ink-faint">
        No rated weeks yet.
      </div>
    );
  }

  const allValues = series.flatMap((entry) =>
    entry.values.filter((value): value is string => value !== null).map(Number),
  );
  const start = Number(startingRating);
  const scale = niceIntegerScale(Math.min(...allValues, start), Math.max(...allValues, start), 5);
  const xFor = (index: number) => positionFor(index, weeks.length, layout.left, plotWidth);
  const yFor = (value: number) =>
    layout.top + ((scale.max - value) / (scale.max - scale.min)) * plotHeight;

  const drawn = series
    .filter((entry) => visible.has(entry.teamKey))
    .slice()
    .sort(
      (left, right) =>
        Number(left.teamKey === selectedTeamKey) - Number(right.teamKey === selectedTeamKey),
    );

  const summary = summaryFor(weeks, series, visible, mode);
  const xLabelY = layout.height - (compact ? 8 : 10);
  const seasonStarts = weeks
    .map((week, index) => ({ week, index }))
    .filter((item) => item.week.is_season_start);
  const weekLabelIndices = selectWeekLabelIndices(
    weeks.length,
    compact ? 6 : 8,
    compact ? 34 : 40,
    xFor,
  );
  // Season labels share their row with nothing else, but a long history needs thinning at 360px.
  const seasonLabelIndices = selectWeekLabelIndices(
    seasonStarts.length,
    compact ? 6 : 12,
    compact ? 34 : 30,
    (position) => xFor(seasonStarts[position].index),
  );

  return (
    <div className="mt-3 rounded-xl border border-line bg-surface p-4" data-chart="elo">
      <svg
        className="block h-auto w-full"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label={summary}
      >
        <title>Elo score history</title>
        <desc>{summary}</desc>

        <rect
          x={layout.left}
          y={layout.top}
          width={plotWidth}
          height={plotHeight}
          rx={4}
          className="fill-chart-plot"
        />

        <g fontSize={compact ? 9 : 10.5} textAnchor="end" className="fill-chart-axis">
          {scale.ticks.map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={layout.left}
                  y1={y}
                  x2={layout.width - layout.right}
                  y2={y}
                  className="stroke-chart-grid"
                  strokeWidth={1}
                />
                <text x={layout.left - 5} y={y + 3} data-axis="value">
                  {formatEloWhole(String(tick))}
                </text>
              </g>
            );
          })}
        </g>

        {start >= scale.min && start <= scale.max ? (
          <g>
            <line
              x1={layout.left}
              y1={yFor(start)}
              x2={layout.width - layout.right}
              y2={yFor(start)}
              className="stroke-chart-start"
              strokeWidth={1.2}
              strokeDasharray="4 4"
            />
            <text
              x={layout.width - layout.right - 3}
              y={yFor(start) - 3}
              textAnchor="end"
              fontSize={compact ? 8.5 : 10}
              className="fill-chart-start-label"
            >
              start {formatEloWhole(startingRating)}
            </text>
          </g>
        ) : null}

        {boundaries.map((boundary) => {
          const x = xFor(boundary.week_index);
          return (
            <g key={`boundary-${boundary.season}`}>
              <line
                x1={x}
                y1={layout.top}
                x2={x}
                y2={layout.height - layout.bottom}
                className="stroke-chart-boundary"
                strokeWidth={1.2}
                strokeDasharray="5 4"
              />
            </g>
          );
        })}

        <g fontSize={compact ? 8.5 : 10.5} textAnchor="middle" className="fill-chart-label-muted">
          {seasonLabelIndices.map((position) => {
            const item = seasonStarts[position];
            return (
              <text
                key={`season-${item.week.season}`}
                x={xFor(item.index)}
                y={compact ? 12 : 14}
                fontWeight={700}
                data-axis="season"
                textAnchor={
                  item.index === 0 ? "start" : item.index === weeks.length - 1 ? "end" : "middle"
                }
              >
                {item.week.season}
              </text>
            );
          })}
        </g>

        <g fontSize={compact ? 8 : 9.5} textAnchor="middle" className="fill-chart-axis">
          {weekLabelIndices.map((index) => (
            <text
              key={`x-${weeks[index].season}-${weeks[index].week}`}
              x={xFor(index)}
              y={xLabelY}
              data-axis="week"
              data-week-index={index}
            >
              W{weeks[index].week}
            </text>
          ))}
        </g>

        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {drawn.flatMap((entry) => {
            const style = seriesStyle(entry.styleIndex);
            const selected = entry.teamKey === selectedTeamKey;
            return segmentsFor(entry.values, xFor, yFor)
              .filter((segment) => segment.length > 1)
              .map((segment, segmentIndex) => (
                <polyline
                  key={`${entry.teamKey}-${segmentIndex}`}
                  data-team-key={entry.teamKey}
                  points={segment.map((point) => `${point.x},${point.y}`).join(" ")}
                  strokeWidth={selected ? 3.4 : 1.8}
                  strokeDasharray={style.dash}
                  opacity={selected || selectedTeamKey === null ? 1 : 0.55}
                  style={{ stroke: style.color }}
                />
              ));
          })}
        </g>

        <g>
          {drawn.flatMap((entry) => {
            const style = seriesStyle(entry.styleIndex);
            const selected = entry.teamKey === selectedTeamKey;
            return entry.values.flatMap((value, index) =>
              value === null
                ? []
                : [
                    <circle
                      key={`${entry.teamKey}-${index}`}
                      data-dot={entry.teamKey}
                      data-week-index={index}
                      cx={xFor(index)}
                      cy={yFor(Number(value))}
                      r={selected ? 2.6 : compact ? 1.4 : 1.6}
                      style={{ fill: style.color }}
                    />,
                  ],
            );
          })}
        </g>

        {compact ? null : (
          <g fontSize={10.5} textAnchor="middle" className="fill-chart-label">
            <text x={layout.left + plotWidth / 2} y={layout.height - 4} fontWeight={600}>
              Week
            </text>
            <text
              x={14}
              y={layout.top + plotHeight / 2}
              fontWeight={600}
              transform={`rotate(-90 14 ${layout.top + plotHeight / 2})`}
            >
              Elo score
            </text>
          </g>
        )}
      </svg>

      <p id="elo-chart-legend-hint" className="mt-3 text-xs text-ink-faint">
        Click a team to hide or show its line. Double-click a team to show only that team.
      </p>
      <ul
        className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3"
        aria-label="Chart series toggles"
        aria-describedby="elo-chart-legend-hint"
      >
        {series.map((entry) => {
          const style = seriesStyle(entry.styleIndex);
          const shown = visible.has(entry.teamKey);
          const selected = entry.teamKey === selectedTeamKey;
          return (
            <li
              key={entry.teamKey}
              data-series-chip={entry.teamKey}
              onDoubleClick={() => onIsolateTeam(entry.teamKey)}
              title={`Show or hide ${entry.name}. Double-click to show only ${entry.name}.`}
              className={`flex min-w-0 items-center gap-2 rounded-xl border px-2 py-1 text-[13px] ${
                selected ? "border-brand-ink bg-brand-soft" : "border-line bg-surface"
              }`}
            >
              <button
                type="button"
                aria-pressed={shown}
                aria-label={`Show or hide ${entry.name} series`}
                onClick={() => onToggleTeam(entry.teamKey)}
                className="shrink-0 rounded-full p-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink"
              >
                <svg width={30} height={10} aria-hidden="true">
                  <line
                    x1={1}
                    y1={5}
                    x2={29}
                    y2={5}
                    strokeWidth={2.2}
                    strokeDasharray={style.dash}
                    strokeLinecap="round"
                    opacity={shown ? 1 : 0.3}
                    style={{ stroke: style.color }}
                  />
                  <circle cx={15} cy={5} r={3} style={{ fill: style.color }} />
                </svg>
              </button>
              <button
                type="button"
                aria-pressed={selected}
                aria-label={`Highlight ${entry.name} ${formatEloValue(entry.current)}`}
                onClick={() => onSelectTeam(entry.teamKey)}
                className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink"
              >
                <span
                  className={`min-w-0 break-words ${shown ? "" : "line-through"} ${
                    selected ? "font-semibold text-brand-ink" : ""
                  }`}
                >
                  {entry.name}
                </span>{" "}
                <span className="shrink-0 tabular-nums text-ink-faint">
                  {formatEloValue(entry.current)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <details className="mt-3">
        <summary className="cursor-pointer text-[13px] font-semibold text-brand-ink">
          View chart data as a table
        </summary>
        <div
          className="relative mt-2 overflow-x-auto rounded-xl border border-line bg-surface"
          tabIndex={0}
          role="region"
          aria-label="Elo score history data table"
        >
          <table className="w-full border-separate border-spacing-0 text-sm">
            <caption className="sr-only">
              Elo score for each team after each chart week, {weeks[0].season} week {weeks[0].week}{" "}
              through {weeks[weeks.length - 1].season} week {weeks[weeks.length - 1].week}.
            </caption>
            <thead>
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 z-10 whitespace-nowrap border-b border-line-strong bg-surface px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint"
                >
                  Team
                </th>
                {weeks.map((week) => (
                  <th
                    key={`${week.season}-${week.week}`}
                    scope="col"
                    className="whitespace-nowrap border-b border-line-strong px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-ink-faint"
                  >
                    {week.season} W{week.week}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={LAST_ROW_NO_DIVIDER}>
              {series.map((entry) => (
                <tr key={entry.teamKey}>
                  <th
                    scope="row"
                    className={`${BODY_CELL_DIVIDER} sticky left-0 z-10 whitespace-nowrap bg-surface px-3 py-2 text-left font-semibold`}
                  >
                    {entry.name}
                  </th>
                  {entry.values.map((value, index) => (
                    <td
                      key={`${entry.teamKey}-${index}`}
                      className={`${BODY_CELL_DIVIDER} whitespace-nowrap px-3 py-2 text-right tabular-nums text-ink-subtle`}
                    >
                      {value === null ? "—" : formatEloValue(value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
