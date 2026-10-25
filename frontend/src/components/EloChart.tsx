import type { EloWeek } from "../api/types";
import { niceValueScale, positionFor, spreadLabelPositions } from "./chartGeometry";
import { formatEloValue } from "./format";
import { seriesStyle } from "./series";

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
  full: { width: 760, height: 420, top: 44, right: 112, bottom: 44, left: 52 },
} as const;

const MODE_LABELS = {
  actual_schedule: "Actual schedule",
  round_robin: "Round robin",
} as const;

interface MarkerProps {
  shape: ReturnType<typeof seriesStyle>["marker"];
  x: number;
  y: number;
  color: string;
  size: number;
}

function Marker({ shape, x, y, color, size }: MarkerProps) {
  switch (shape) {
    case "circle":
      return <circle cx={x} cy={y} r={size} fill={color} />;
    case "square":
      return <rect x={x - size} y={y - size} width={size * 2} height={size * 2} fill={color} />;
    case "triangle":
      return (
        <path
          d={`M ${x} ${y - size} L ${x + size} ${y + size} L ${x - size} ${y + size} Z`}
          fill={color}
        />
      );
    case "diamond":
      return (
        <path
          d={`M ${x} ${y - size} L ${x + size} ${y} L ${x} ${y + size} L ${x - size} ${y} Z`}
          fill={color}
        />
      );
    case "plus":
      return (
        <path
          d={`M ${x - size} ${y} H ${x + size} M ${x} ${y - size} V ${y + size}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
        />
      );
    case "cross":
      return (
        <path
          d={`M ${x - size} ${y - size} L ${x + size} ${y + size} M ${x + size} ${y - size} L ${x - size} ${y + size}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
        />
      );
  }
}

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
  const cupWeeks = weeks.filter((week) => week.is_cup_week);
  const cupNote =
    cupWeeks.length === 0
      ? ""
      : mode === "actual_schedule"
        ? " Cup weeks are marked and skipped in actual schedule."
        : " Cup weeks are marked and count in round robin.";
  return `Elo score history, ${MODE_LABELS[mode]}, ${weeks.length} chart weeks from ${first.season} week ${first.week} to ${last.season} week ${last.week}. ${leader}${cupNote} Ratings regress toward the starting rating before each new season.`;
}

/**
 * Running Elo chart drawn as dependency-free inline SVG.
 *
 * Season starts get vertical rules and labels, cup weeks get a distinct marker, and non-null
 * values are joined in segments so a franchise that missed a season has a real gap. Series differ
 * by color, dash pattern, and marker shape; the selected team is drawn last and thicker, and
 * legend buttons toggle visibility or select a team. The `<details>` table is the chart's
 * non-visual equivalent and includes every exact value and cup-week header.
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
      <div className="mt-3 rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        No rated weeks yet.
      </div>
    );
  }

  const allValues = series.flatMap((entry) =>
    entry.values.filter((value): value is string => value !== null).map(Number),
  );
  const start = Number(startingRating);
  const scale = niceValueScale(Math.min(...allValues, start), Math.max(...allValues, start), 5);
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

  const endLabels = compact
    ? []
    : drawn
        .map((entry) => ({ entry, value: lastValue(entry) }))
        .filter((item): item is { entry: EloChartSeries; value: string } => item.value !== null)
        .sort((left, right) => Number(left.value) - Number(right.value))
        .map((item) => ({ entry: item.entry, y: yFor(Number(item.value)) }));
  const endLabelY = spreadLabelPositions(
    endLabels.map((item) => item.y),
    16,
    layout.top,
    layout.height - layout.bottom,
  );

  const summary = summaryFor(weeks, series, visible, mode);
  const xLabelY = layout.height - (compact ? 8 : 10);
  const seasonStarts = weeks
    .map((week, index) => ({ week, index }))
    .filter((item) => item.week.is_season_start);
  const labelStep = Math.max(1, Math.ceil(weeks.length / (compact ? 6 : 12)));
  const showXLabel = (index: number) =>
    index === 0 ||
    index === weeks.length - 1 ||
    index % labelStep === 0 ||
    weeks[index].is_season_start;

  return (
    <div className="mt-3 rounded-xl border border-gray-200 bg-white p-4">
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
          fill="#f8fafc"
          rx={4}
        />

        <g fontSize={compact ? 9 : 10.5} fill="#6b7280" textAnchor="end">
          {scale.ticks.map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={layout.left}
                  y1={y}
                  x2={layout.width - layout.right}
                  y2={y}
                  stroke="#e5e7eb"
                  strokeWidth={1}
                />
                <text x={layout.left - 5} y={y + 3}>
                  {formatEloValue(String(tick))}
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
              stroke="#94a3b8"
              strokeWidth={1.2}
              strokeDasharray="4 4"
            />
            <text
              x={layout.width - layout.right - 3}
              y={yFor(start) - 3}
              textAnchor="end"
              fontSize={compact ? 8.5 : 10}
              fill="#64748b"
            >
              start {formatEloValue(startingRating)}
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
                stroke="#cbd5e1"
                strokeWidth={1.2}
                strokeDasharray="5 4"
              />
            </g>
          );
        })}

        {weeks.map((week, index) =>
          week.is_cup_week ? (
            <g
              key={`cup-${week.season}-${week.week}`}
              data-cup-week={`${week.season}-${week.week}`}
            >
              <line
                x1={xFor(index)}
                y1={layout.top}
                x2={xFor(index)}
                y2={layout.height - layout.bottom}
                stroke={mode === "actual_schedule" ? "#b45309" : "#0f766e"}
                strokeWidth={1.2}
                strokeDasharray="2 3"
              />
              <text
                x={xFor(index)}
                y={layout.top - (compact ? 5 : 7)}
                textAnchor="middle"
                fontSize={compact ? 7.5 : 9}
                fill={mode === "actual_schedule" ? "#92400e" : "#115e59"}
              >
                Cup
              </text>
            </g>
          ) : null,
        )}

        <g fontSize={compact ? 8.5 : 10.5} fill="#4b5563" textAnchor="middle">
          {seasonStarts.map((item) => (
            <text
              key={`season-${item.week.season}`}
              x={xFor(item.index)}
              y={compact ? 12 : 14}
              fontWeight={700}
              textAnchor={item.index === 0 ? "start" : "middle"}
            >
              {item.week.season}
            </text>
          ))}
        </g>

        <g fontSize={compact ? 8 : 9.5} fill="#6b7280" textAnchor="middle">
          {weeks.map((week, index) =>
            showXLabel(index) ? (
              <text key={`x-${week.season}-${week.week}`} x={xFor(index)} y={xLabelY}>
                W{week.week}
              </text>
            ) : null,
          )}
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
                  stroke={style.color}
                  strokeWidth={selected ? 3.4 : 1.8}
                  strokeDasharray={style.dash}
                  opacity={selected || selectedTeamKey === null ? 1 : 0.55}
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
                    <Marker
                      key={`${entry.teamKey}-${index}`}
                      shape={style.marker}
                      x={xFor(index)}
                      y={yFor(Number(value))}
                      color={style.color}
                      size={selected ? 4 : compact ? 2.2 : 2.8}
                    />,
                  ],
            );
          })}
        </g>

        {endLabels.map((item, index) => (
          <text
            key={item.entry.teamKey}
            x={layout.width - layout.right + 8}
            y={endLabelY[index] + 4}
            fontSize={11}
            fontWeight={600}
            fill={seriesStyle(item.entry.styleIndex).color}
          >
            {item.entry.name} {formatEloValue(lastValue(item.entry) ?? item.entry.current)}
          </text>
        ))}

        {compact ? null : (
          <g fontSize={10.5} fill="#374151" textAnchor="middle">
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

      <p id="elo-chart-legend-hint" className="mt-3 text-xs text-gray-500">
        Click a team to hide or show its line. Double-click a team to show only that team.
      </p>
      <ul
        className="mt-2 flex flex-wrap gap-2"
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
              onDoubleClick={() => onIsolateTeam(entry.teamKey)}
              title={`Show or hide ${entry.name}. Double-click to show only ${entry.name}.`}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[13px] ${
                selected ? "border-brand bg-brand-foreground" : "border-gray-200 bg-white"
              }`}
            >
              <button
                type="button"
                aria-pressed={shown}
                aria-label={`Show or hide ${entry.name} series`}
                onClick={() => onToggleTeam(entry.teamKey)}
                className="rounded-full p-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
              >
                <svg width={30} height={10} aria-hidden="true">
                  <line
                    x1={1}
                    y1={5}
                    x2={29}
                    y2={5}
                    stroke={style.color}
                    strokeWidth={2.2}
                    strokeDasharray={style.dash}
                    strokeLinecap="round"
                    opacity={shown ? 1 : 0.3}
                  />
                  <Marker shape={style.marker} x={15} y={5} color={style.color} size={3} />
                </svg>
              </button>
              <button
                type="button"
                aria-pressed={selected}
                aria-label={`Highlight ${entry.name}`}
                onClick={() => onSelectTeam(entry.teamKey)}
                className={`flex items-center gap-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                  shown ? "" : "line-through"
                }`}
              >
                <span className={selected ? "font-semibold text-brand" : ""}>{entry.name}</span>
                <span className="tabular-nums text-gray-500">{formatEloValue(entry.current)}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <details className="mt-3">
        <summary className="cursor-pointer text-[13px] font-semibold text-brand">
          View chart data as a table
        </summary>
        <div
          className="relative mt-2 overflow-x-auto rounded-xl border border-gray-200 bg-white"
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
                  className="sticky left-0 z-10 whitespace-nowrap border-b border-gray-300 bg-white px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                >
                  Team
                </th>
                {weeks.map((week) => (
                  <th
                    key={`${week.season}-${week.week}`}
                    scope="col"
                    className="whitespace-nowrap border-b border-gray-300 px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                  >
                    {week.season} W{week.week}
                    {week.is_cup_week ? " (cup)" : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {series.map((entry) => (
                <tr
                  key={entry.teamKey}
                  className="[&>th]:border-b [&>td]:border-b [&>th]:border-gray-200 [&>td]:border-gray-200 last:[&>th]:border-b-0 last:[&>td]:border-b-0"
                >
                  <th
                    scope="row"
                    className="sticky left-0 z-10 whitespace-nowrap bg-white px-3 py-2 text-left font-semibold"
                  >
                    {entry.name}
                  </th>
                  {entry.values.map((value, index) => (
                    <td
                      key={`${entry.teamKey}-${index}`}
                      className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-600"
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
