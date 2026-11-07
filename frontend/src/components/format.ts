import type { ProbabilityInterval } from "../api/types";

/**
 * Display formatting helpers for the standings UI, Elo ratings, records, and odds.
 *
 * The API serializes score and Victory Point values as decimal strings (ARCHITECTURE.md §8).
 * These helpers only reshape those strings: VP never carries a "+" prefix, negative VP keeps a
 * leading "-", zero renders as a plain "0", and trailing zeros are trimmed ("2.50" -> "2.5").
 * VP is never parsed to a float for display, so no binary-float error can reach the screen.
 */

export type VPTone = "pos" | "neg" | "zero";

/** Format a decimal VP string for display. */
export function formatVP(value: string): string {
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = negative ? trimmed.slice(1) : trimmed;
  const dot = digits.indexOf(".");
  const wholeRaw = dot === -1 ? digits : digits.slice(0, dot);
  const whole = wholeRaw.replace(/^0+(?=\d)/, "") || "0";
  const fraction = (dot === -1 ? "" : digits.slice(dot + 1)).replace(/0+$/, "");
  const isZero = whole === "0" && fraction === "";
  const sign = negative && !isZero ? "-" : "";
  return fraction === "" ? `${sign}${whole}` : `${sign}${whole}.${fraction}`;
}

/** Format a points-for string with exactly two decimals ("812.3" -> "812.30"). */
export function formatPoints(value: string): string {
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = negative ? trimmed.slice(1) : trimmed;
  const dot = digits.indexOf(".");
  const whole = (dot === -1 ? digits : digits.slice(0, dot)) || "0";
  const fraction = dot === -1 ? "" : digits.slice(dot + 1);
  return `${negative ? "-" : ""}${whole}.${`${fraction}00`.slice(0, 2)}`;
}

export function vpTone(value: string): VPTone {
  const formatted = formatVP(value);
  if (formatted.startsWith("-")) {
    return "neg";
  }
  return formatted === "0" ? "zero" : "pos";
}

/** A text class for the VP tone; the sign is always present, so color is never the only cue. */
export function vpToneClass(tone: VPTone): string {
  if (tone === "neg") {
    return "text-danger-ink-soft";
  }
  if (tone === "zero") {
    return "text-ink-faint";
  }
  return "text-brand-ink";
}

/** Parse a decimal string for chart geometry and sorting only — never for equality. */
export function toNumber(value: string): number {
  return Number(value);
}

/** The H2H record column: "W-L" normally, "W-L-T" only when the season has an H2H tie. */
export function formatRecord(
  row: { wins: number; losses: number; ties: number },
  showTies: boolean,
): string {
  const base = `${row.wins}-${row.losses}`;
  return showTies ? `${base}-${row.ties}` : base;
}

/** Round an Elo rating string to the nearest whole number for the current-scores table. */
export function formatEloWhole(value: string): string {
  const rounded = Math.round(Number(value));
  return String(Object.is(rounded, -0) ? 0 : rounded);
}

/** Format an Elo rating for the chart and peak/low columns, keeping exactly two decimals. */
export function formatEloValue(value: string): string {
  const number = Number(value);
  const fixed = number.toFixed(2);
  return fixed === "-0.00" ? "0.00" : fixed;
}

/**
 * Format an Elo rating change with exactly two decimals and an explicit plus sign for gains.
 * The sign is text, so a gain and a loss are distinguishable without color.
 */
export function formatEloChange(value: string): string {
  const number = Number(value);
  const fixed = number.toFixed(2);
  if (fixed === "-0.00") {
    return "0.00";
  }
  return number > 0 ? `+${fixed}` : fixed;
}

const KEYCAP_DIGITS = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"] as const;
const KEYCAP_TEN = "🔟";

/**
 * The visible count prefix for a record tally: nothing for one, keycap digits for 2-9, `🔟` for
 * ten, and keycap digits for larger counts. The count is left out entirely for zero (the caller
 * hides the tally), so `1` renders as just the record emoji while `3` renders as `3️⃣`.
 */
export function formatRecordCount(count: number): string {
  if (count <= 1) {
    return "";
  }
  if (count === 10) {
    return KEYCAP_TEN;
  }
  return String(count)
    .split("")
    .map((digit) => KEYCAP_DIGITS[Number(digit)])
    .join("");
}

/**
 * Formatting helpers for the admin seasons table.
 *
 * The API sends `last_refreshed_at` as an ISO UTC instant (or null). A missing value means the
 * season has never synced through the provider; the UI shows "Never" rather than an empty cell.
 */
export function formatLastRefreshed(value: string | null): string {
  if (value === null) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Never";
  }
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Render the projection as-of instant in the browser's local time, or the raw value if invalid. */
export function formatProjectionAsOf(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** Whole-percent label; a real sub-1% value is not flattened to "0%". */
export function percentLabel(value: string): string {
  const number = Number(value);
  if (number > 0 && number < 0.005) {
    return "<1%";
  }
  if (number < 1 && number >= 0.995) {
    return ">99%";
  }
  return `${Math.round(number * 100)}%`;
}

/** Spoken percentage for an accessible name, with the edge cases spelled out. */
export function spokenPercent(value: string): string {
  const number = Number(value);
  if (number > 0 && number < 0.005) {
    return "less than 1 percent";
  }
  if (number < 1 && number >= 0.995) {
    return "more than 99 percent";
  }
  return `${Math.round(number * 100)} percent`;
}

/** Visible 95% interval line, e.g. "83–85%". */
export function intervalLabel(probability: ProbabilityInterval): string {
  const low = Math.round(Number(probability.low) * 100);
  const high = Math.round(Number(probability.high) * 100);
  return `${low}–${high}%`;
}

/** Accessible interval description including the estimate and both bounds. */
export function probabilityDescription(label: string, probability: ProbabilityInterval): string {
  return `${label} ${spokenPercent(probability.probability)}, 95 percent interval ${spokenPercent(
    probability.low,
  )} to ${spokenPercent(probability.high)}`;
}
