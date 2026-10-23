/**
 * Chart series styling. Color alone never distinguishes a series: each index pairs a color with a
 * line dash pattern and a marker shape, so the series stay distinguishable in grayscale or with a
 * color-vision deficiency, and the pairing is reused by the legend, the table tags, and the chart.
 */

export type MarkerShape = "circle" | "square" | "triangle" | "diamond" | "plus" | "cross";

export interface SeriesStyle {
  color: string;
  dash: string | undefined;
  marker: MarkerShape;
}

export const SERIES_STYLES: readonly SeriesStyle[] = [
  { color: "#0f766e", dash: undefined, marker: "circle" },
  { color: "#b45309", dash: "8 5", marker: "square" },
  { color: "#1d4ed8", dash: "1.5 5", marker: "triangle" },
  { color: "#7e22ce", dash: "11 4 2 4", marker: "diamond" },
  { color: "#be123c", dash: "5 4", marker: "plus" },
  { color: "#4b5563", dash: "14 5", marker: "cross" },
  { color: "#0891b2", dash: "3 4", marker: "circle" },
  { color: "#a16207", dash: "6 4", marker: "square" },
  { color: "#4338ca", dash: "2 4", marker: "triangle" },
  { color: "#9f1239", dash: "10 4 2 4", marker: "diamond" },
  { color: "#4d7c0f", dash: "9 3", marker: "plus" },
  { color: "#7c2d12", dash: "4 3 1 3", marker: "cross" },
];

/** Wraps around for leagues with more teams than preset styles. */
export function seriesStyle(index: number): SeriesStyle {
  return SERIES_STYLES[index % SERIES_STYLES.length];
}
