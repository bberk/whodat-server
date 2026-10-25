import type { ProbabilityInterval } from "../api/types";

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
