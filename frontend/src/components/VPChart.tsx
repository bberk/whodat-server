import { niceScale, positionFor, spreadLabelPositions } from "./chartGeometry";
import { formatVP, toNumber } from "./format";
import { seriesStyle } from "./series";

export interface ChartSeries {
  teamId: number;
  teamName: string;
  /** Index into the shared series style table (color + dash + marker). */
  styleIndex: number;
  /** Cumulative VP per week, as the API serializes them (decimal strings). */
  cumulative: string[];
}

export interface VPChartProps {
  weeks: number[];
  series: ChartSeries[];
  visibleTeamIds: readonly number[];
  selectedTeamId: number | null;
  onToggleTeam: (teamId: number) => void;
  /** Compact geometry (labels trimmed) for narrow viewports; the layout is chosen by the page. */
  compact: boolean;
}

const LAYOUT = {
  compact: { width: 360, height: 280, top: 12, right: 10, bottom: 28, left: 34 },
  full: { width: 720, height: 380, top: 16, right: 96, bottom: 38, left: 44 },
} as const;

function lastValue(series: ChartSeries): string {
  return series.cumulative[series.cumulative.length - 1];
}

interface MarkerProps {
  shape: ReturnType<typeof seriesStyle>["marker"];
  x: number;
  y: number;
  color: string;
  size: number;
}

/** One point marker. The shape is the second non-color cue that identifies a series. */
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

/**
 * Cumulative VP line chart, drawn as dependency-free inline SVG. Series differ by color, dash
 * pattern, and marker shape; the selected team is drawn last and thicker; legend chips toggle
 * series. The `<details>` table is the chart's non-visual equivalent.
 */
export function VPChart({
  weeks,
  series,
  visibleTeamIds,
  selectedTeamId,
  onToggleTeam,
  compact,
}: VPChartProps) {
  const layout = compact ? LAYOUT.compact : LAYOUT.full;
  const plotWidth = layout.width - layout.left - layout.right;
  const plotHeight = layout.height - layout.top - layout.bottom;
  const visible = new Set(visibleTeamIds);

  if (weeks.length === 0 || series.length === 0) {
    return (
      <div className="mt-3 rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        No chart data for this season yet.
      </div>
    );
  }

  const allValues = series.flatMap((entry) => entry.cumulative.map(toNumber));
  const scale = niceScale(Math.min(...allValues), Math.max(...allValues), 4);
  const xFor = (index: number) => positionFor(index, weeks.length, layout.left, plotWidth);
  const yFor = (value: number) =>
    layout.top + ((scale.max - value) / (scale.max - scale.min)) * plotHeight;

  const drawn = series
    .filter((entry) => visible.has(entry.teamId))
    .slice()
    .sort((a, b) => Number(a.teamId === selectedTeamId) - Number(b.teamId === selectedTeamId));

  const endLabels = compact
    ? []
    : drawn
        .slice()
        .sort((a, b) => toNumber(lastValue(a)) - toNumber(lastValue(b)))
        .map((entry) => ({ entry, y: yFor(toNumber(lastValue(entry))) }));
  const endLabelY = spreadLabelPositions(
    endLabels.map((item) => item.y),
    16,
    layout.top,
    layout.height - layout.bottom,
  );

  const ranked = drawn.slice().sort((a, b) => toNumber(lastValue(b)) - toNumber(lastValue(a)));
  const summary = [
    `Line chart of cumulative victory points, weeks ${weeks[0]} to ${weeks[weeks.length - 1]}.`,
    ranked.map((entry) => `${entry.teamName} ${formatVP(lastValue(entry))}`).join(", "),
  ].join(" ");
  const xLabelY = layout.height - (compact ? 8 : 10);

  return (
    <div className="mt-3 rounded-xl border border-gray-200 bg-white p-4">
      <svg
        className="block h-auto w-full"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label={summary}
      >
        <title>Cumulative victory points by week</title>
        <g fontSize={compact ? 9 : 11} fill="#6b7280" textAnchor="end">
          {scale.ticks.map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={layout.left}
                  y1={y}
                  x2={layout.width - layout.right}
                  y2={y}
                  stroke={tick === 0 ? "#9ca3af" : "#e5e7eb"}
                  strokeWidth={tick === 0 ? 1.2 : 1}
                />
                <text x={layout.left - 4} y={y + 3}>
                  {formatVP(String(tick))}
                </text>
              </g>
            );
          })}
        </g>
        <g fontSize={compact ? 9.5 : 11} fill="#6b7280" textAnchor="middle">
          {weeks.map((week, index) => (
            <text key={week} x={xFor(index)} y={xLabelY}>
              W{week}
            </text>
          ))}
        </g>
        {compact ? null : (
          <g fontSize={11} fill="#374151" textAnchor="middle">
            <text x={layout.left + plotWidth / 2} y={layout.height - 4} fontWeight={600}>
              Week
            </text>
            <text
              x={14}
              y={layout.top + plotHeight / 2}
              fontWeight={600}
              transform={`rotate(-90 14 ${layout.top + plotHeight / 2})`}
            >
              Cumulative VP
            </text>
          </g>
        )}
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {drawn.map((entry) => {
            const style = seriesStyle(entry.styleIndex);
            const selected = entry.teamId === selectedTeamId;
            return (
              <polyline
                key={entry.teamId}
                data-team-id={entry.teamId}
                points={entry.cumulative
                  .map((value, index) => `${xFor(index)},${yFor(toNumber(value))}`)
                  .join(" ")}
                stroke={style.color}
                strokeWidth={selected ? 3.2 : 2.2}
                strokeDasharray={style.dash}
              />
            );
          })}
        </g>
        <g>
          {drawn.map((entry) => {
            const style = seriesStyle(entry.styleIndex);
            const size = entry.teamId === selectedTeamId ? 4.6 : compact ? 3.4 : 4;
            return entry.cumulative.map((value, index) => (
              <Marker
                key={`${entry.teamId}-${weeks[index]}`}
                shape={style.marker}
                x={xFor(index)}
                y={yFor(toNumber(value))}
                color={style.color}
                size={size}
              />
            ));
          })}
        </g>
        {endLabels.map((item, index) => (
          <text
            key={item.entry.teamId}
            x={layout.width - layout.right + 8}
            y={endLabelY[index] + 4}
            fontSize={11.5}
            fontWeight={600}
            fill={seriesStyle(item.entry.styleIndex).color}
          >
            {item.entry.teamName} {formatVP(lastValue(item.entry))}
          </text>
        ))}
      </svg>

      <ul className="mt-4 flex flex-wrap gap-2" aria-label="Chart series toggles">
        {series.map((entry) => {
          const style = seriesStyle(entry.styleIndex);
          const shown = visible.has(entry.teamId);
          const selected = entry.teamId === selectedTeamId;
          return (
            <li key={entry.teamId}>
              <button
                type="button"
                aria-pressed={shown}
                onClick={() => onToggleTeam(entry.teamId)}
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                  selected ? "border-brand bg-brand-foreground" : "border-gray-200 bg-white"
                } ${shown ? "text-gray-700" : "text-gray-400 line-through"}`}
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
                  />
                  <Marker shape={style.marker} x={15} y={5} color={style.color} size={3} />
                </svg>
                <span className={selected ? "font-semibold text-brand" : ""}>{entry.teamName}</span>
                <span className="tabular-nums text-gray-500">{formatVP(lastValue(entry))}</span>
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
          aria-label="Cumulative VP data table"
        >
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Cumulative victory points per team, weeks {weeks[0]} to {weeks[weeks.length - 1]}.
            </caption>
            <thead>
              <tr className="border-b border-gray-300">
                <th
                  scope="col"
                  className="whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                >
                  Team
                </th>
                {weeks.map((week) => (
                  <th
                    key={week}
                    scope="col"
                    className="whitespace-nowrap px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                  >
                    W{week}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {series.map((entry) => (
                <tr key={entry.teamId} className="border-b border-gray-200 last:border-b-0">
                  <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-semibold">
                    {entry.teamName}
                  </th>
                  {entry.cumulative.map((value, index) => (
                    <td
                      key={`${entry.teamId}-${index}`}
                      className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-gray-600"
                    >
                      {formatVP(value)}
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
