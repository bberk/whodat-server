/**
 * Simulation controls and their explicit parsing.
 *
 * The controls are plain text inputs: the team-strength weight accepts any numeric string the
 * browser can cast (for example ".25", "1.", or "0.25") and is validated only by range, so a
 * leading zero or an HTML number step is never required. Every value is parsed here, not by the
 * browser, so the frontend and the exact-Decimal backend agree about what is valid.
 */

/** Iterations a first run uses when the member has not changed the field. */
export const DEFAULT_ITERATIONS = 10_000;
/** Smallest accepted iteration count. */
export const MIN_ITERATIONS = 1;
/** Largest iteration count a regular member may request. */
export const MEMBER_MAX_ITERATIONS = 10_000;
/** Largest iteration count an admin may request. */
export const ADMIN_MAX_ITERATIONS = 100_000;
/** Largest accepted explicit seed. */
export const MAX_SEED = 2_147_483_647;
/** Smallest accepted team-strength weight. */
export const MIN_STRENGTH_WEIGHT = 0;
/** Largest accepted team-strength weight. */
export const MAX_STRENGTH_WEIGHT = 10;
/** Decimal places accepted for a team-strength weight, matching the backend's exact Decimal bound. */
export const MAX_WEIGHT_DECIMALS = 18;
/** Default team-strength weight, the shrunk model. */
export const DEFAULT_STRENGTH_WEIGHT = "1";

export interface ControlText {
  iterations: string;
  strengthWeight: string;
  seed: string;
}

/** Count decimal places after normalizing trailing zeros, as `Decimal.normalize()` does. */
function normalizedDecimalPlaces(text: string): number {
  const match = /^[+-]?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
  if (match === null) {
    return 0;
  }
  const digits = `${match[1] ?? ""}${match[2] ?? ""}`.replace(/^0+/, "");
  if (digits === "") {
    return 0;
  }
  const trimmed = digits.replace(/0+$/, "");
  const trailingZeros = digits.length - trimmed.length;
  const exponent = Number(match[3] ?? "0") - (match[2] ?? "").length + trailingZeros;
  return Math.max(0, -exponent);
}

export interface PlayoffOddsRequest {
  iterations: number;
  /** The trimmed numeric text the backend parses as an exact Decimal. */
  strengthWeight: string;
  seed?: number;
}

export type ParsedControls =
  { ok: true; request: PlayoffOddsRequest } | { ok: false; message: string };

/** Return the iteration cap for an authenticated role; a missing role is a regular member. */
export function maxIterationsForRole(role: string | null | undefined): number {
  return role === "admin" ? ADMIN_MAX_ITERATIONS : MEMBER_MAX_ITERATIONS;
}

/** Decimal numeric text the backend's `Decimal` parser also accepts. */
const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/**
 * Parse and validate the three simulation controls.
 *
 * Iterations and the optional seed are whole decimal numbers; the strength weight is any decimal
 * numeric string (including `.25`, `1.`, and `1e-1`), then range-checked to 0..10. An invalid value
 * returns one actionable message and never reaches the API.
 */
export function parseControls(text: ControlText, maxIterations: number): ParsedControls {
  const iterationText = text.iterations.trim();
  if (!/^\d+$/.test(iterationText)) {
    return {
      ok: false,
      message: `Enter a whole number of simulations from ${MIN_ITERATIONS.toLocaleString()} to ${maxIterations.toLocaleString()}.`,
    };
  }
  const iterations = Number(iterationText);
  if (
    !Number.isSafeInteger(iterations) ||
    iterations < MIN_ITERATIONS ||
    iterations > maxIterations
  ) {
    return {
      ok: false,
      message: `Enter a whole number of simulations from ${MIN_ITERATIONS.toLocaleString()} to ${maxIterations.toLocaleString()}.`,
    };
  }

  const weightText = text.strengthWeight.trim();
  const weight = Number(weightText);
  if (
    !DECIMAL_PATTERN.test(weightText) ||
    !Number.isFinite(weight) ||
    weight < MIN_STRENGTH_WEIGHT ||
    weight > MAX_STRENGTH_WEIGHT
  ) {
    return {
      ok: false,
      message: `Enter a team strength weight from ${MIN_STRENGTH_WEIGHT} to ${MAX_STRENGTH_WEIGHT}, for example .25 or 1.`,
    };
  }
  if (normalizedDecimalPlaces(weightText) > MAX_WEIGHT_DECIMALS) {
    return {
      ok: false,
      message: `Enter a team strength weight with at most ${MAX_WEIGHT_DECIMALS} decimal places.`,
    };
  }

  const seedText = text.seed.trim();
  if (seedText === "") {
    return { ok: true, request: { iterations, strengthWeight: weightText } };
  }
  if (!/^\d+$/.test(seedText)) {
    return {
      ok: false,
      message: `Enter a whole seed from 0 to ${MAX_SEED.toLocaleString()}, or leave it blank.`,
    };
  }
  const seed = Number(seedText);
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > MAX_SEED) {
    return {
      ok: false,
      message: `Enter a whole seed from 0 to ${MAX_SEED.toLocaleString()}, or leave it blank.`,
    };
  }
  return { ok: true, request: { iterations, strengthWeight: weightText, seed } };
}
