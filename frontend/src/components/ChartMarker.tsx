import type { seriesStyle } from "./series";

export interface ChartMarkerProps {
  shape: ReturnType<typeof seriesStyle>["marker"];
  x: number;
  y: number;
  color: string;
  size: number;
}

/** One point marker. The shape is the second non-color cue that identifies a series. */
export function ChartMarker({ shape, x, y, color, size }: ChartMarkerProps) {
  switch (shape) {
    case "circle":
      return <circle cx={x} cy={y} r={size} style={{ fill: color }} />;
    case "square":
      return (
        <rect
          x={x - size}
          y={y - size}
          width={size * 2}
          height={size * 2}
          style={{ fill: color }}
        />
      );
    case "triangle":
      return (
        <path
          d={`M ${x} ${y - size} L ${x + size} ${y + size} L ${x - size} ${y + size} Z`}
          style={{ fill: color }}
        />
      );
    case "diamond":
      return (
        <path
          d={`M ${x} ${y - size} L ${x + size} ${y} L ${x} ${y + size} L ${x - size} ${y} Z`}
          style={{ fill: color }}
        />
      );
    case "plus":
      return (
        <path
          d={`M ${x - size} ${y} H ${x + size} M ${x} ${y - size} V ${y + size}`}
          fill="none"
          style={{ stroke: color }}
          strokeWidth={2}
          strokeLinecap="round"
        />
      );
    case "cross":
      return (
        <path
          d={`M ${x - size} ${y - size} L ${x + size} ${y + size} M ${x + size} ${y - size} L ${x - size} ${y + size}`}
          fill="none"
          style={{ stroke: color }}
          strokeWidth={2}
          strokeLinecap="round"
        />
      );
  }
}
