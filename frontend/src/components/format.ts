/**
 * Display formatting for the standings UI.
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
    return "text-red-700";
  }
  if (tone === "zero") {
    return "text-gray-500";
  }
  return "text-brand";
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
