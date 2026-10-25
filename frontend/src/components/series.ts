/**
 * Chart series styling. Color alone never distinguishes a series: each index pairs a color with a
 * line dash pattern and a marker shape, so the series stay distinguishable in grayscale or with a
 * color-vision deficiency, and the pairing is reused by the legend, the table tags, and the chart.
 *
 * Colors are CSS variables rather than fixed hex values: `src/index.css` defines a light palette and
 * a separate, brighter dark palette, so the same index stays legible on either surface and the
 * chart never re-renders just because the theme changed.
 */

export type MarkerShape = "circle" | "square" | "triangle" | "diamond" | "plus" | "cross";

export interface SeriesStyle {
  color: string;
  dash: string | undefined;
  marker: MarkerShape;
}

export const SERIES_STYLES: readonly SeriesStyle[] = [
  { color: "var(--series-0)", dash: undefined, marker: "circle" },
  { color: "var(--series-1)", dash: "8 5", marker: "square" },
  { color: "var(--series-2)", dash: "1.5 5", marker: "triangle" },
  { color: "var(--series-3)", dash: "11 4 2 4", marker: "diamond" },
  { color: "var(--series-4)", dash: "5 4", marker: "plus" },
  { color: "var(--series-5)", dash: "14 5", marker: "cross" },
  { color: "var(--series-6)", dash: "3 4", marker: "circle" },
  { color: "var(--series-7)", dash: "6 4", marker: "square" },
  { color: "var(--series-8)", dash: "2 4", marker: "triangle" },
  { color: "var(--series-9)", dash: "10 4 2 4", marker: "diamond" },
  { color: "var(--series-10)", dash: "9 3", marker: "plus" },
  { color: "var(--series-11)", dash: "4 3 1 3", marker: "cross" },
];

/** Wraps around for leagues with more teams than preset styles. */
export function seriesStyle(index: number): SeriesStyle {
  return SERIES_STYLES[index % SERIES_STYLES.length];
}
