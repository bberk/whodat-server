/**
 * Formatting helpers for Trade Tracker display, auction budgets, and dates.
 */

export type DollarTone = "pos" | "neg" | "zero";

/**
 * Format an auction dollar amount with exact two-decimal precision.
 *
 * @param value String or numeric dollar representation.
 * @param options.showPlus Whether to prefix positive amounts with "+" (e.g. "+$5.00").
 */
export function formatAuctionDollars(
  value: string | number,
  options: { showPlus?: boolean } = {},
): string {
  const str = typeof value === "number" ? value.toFixed(2) : String(value).trim();
  const negative = str.startsWith("-");
  const clean = negative ? str.slice(1) : str;

  // Split whole and fractional parts
  const dot = clean.indexOf(".");
  const wholeRaw = dot === -1 ? clean : clean.slice(0, dot);
  const whole = wholeRaw.replace(/^0+(?=\d)/, "") || "0";
  const fraction = dot === -1 ? "00" : (clean.slice(dot + 1) + "00").slice(0, 2);

  const isZero = whole === "0" && fraction === "00";
  if (isZero) {
    return "$0.00";
  }

  if (negative) {
    return `-$${whole}.${fraction}`;
  }

  return options.showPlus ? `+$${whole}.${fraction}` : `$${whole}.${fraction}`;
}

/**
 * Determine the visual tone of an auction dollar delta.
 */
export function dollarTone(value: string | number): DollarTone {
  const str = typeof value === "number" ? value.toFixed(2) : String(value).trim();
  if (str.startsWith("-")) {
    const num = Number(str);
    return num === 0 ? "zero" : "neg";
  }
  const num = Number(str);
  return num === 0 ? "zero" : "pos";
}

/**
 * Text color styling for an auction dollar tone.
 */
export function dollarToneClass(tone: DollarTone): string {
  if (tone === "neg") {
    return "text-danger-ink font-semibold";
  }
  if (tone === "pos") {
    return "text-brand-ink font-semibold";
  }
  return "text-ink-muted";
}

/**
 * Badge styling for auction dollar deltas.
 */
export function dollarBadgeClass(tone: DollarTone): string {
  if (tone === "neg") {
    return "bg-danger-surface text-danger-ink border border-danger-line";
  }
  if (tone === "pos") {
    return "bg-brand-soft text-brand-ink border border-brand-soft-line";
  }
  return "bg-surface-strong text-ink-muted border border-line";
}

/**
 * Format an ISO date string into a consistent UTC display format (e.g. "Nov 7, 2026").
 */
export function formatTradeDate(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    if (Number.isNaN(date.getTime())) {
      return isoDate;
    }
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(date);
  } catch {
    return isoDate;
  }
}
