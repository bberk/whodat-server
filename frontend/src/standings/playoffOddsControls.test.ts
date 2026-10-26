import { describe, expect, it } from "vitest";

import {
  ADMIN_MAX_ITERATIONS,
  DEFAULT_ITERATIONS,
  MAX_SEED,
  MEMBER_MAX_ITERATIONS,
  maxIterationsForRole,
  parseControls,
} from "./playoffOddsControls";

function controls(
  overrides: Partial<{ iterations: string; strengthWeight: string; seed: string }> = {},
) {
  return {
    iterations: String(DEFAULT_ITERATIONS),
    strengthWeight: "1",
    seed: "",
    ...overrides,
  };
}

describe("playoffOddsControls", () => {
  it("returns the role-specific iteration cap", () => {
    expect(maxIterationsForRole("admin")).toBe(ADMIN_MAX_ITERATIONS);
    expect(maxIterationsForRole("member")).toBe(MEMBER_MAX_ITERATIONS);
    expect(maxIterationsForRole(null)).toBe(MEMBER_MAX_ITERATIONS);
  });

  it("accepts every castable weight form without a leading zero or step", () => {
    for (const weight of [".25", "0.25", "1.", "1", "0", "10", "1e-1"]) {
      const parsed = parseControls(controls({ strengthWeight: weight }), MEMBER_MAX_ITERATIONS);
      expect(parsed).toEqual({
        ok: true,
        request: { iterations: DEFAULT_ITERATIONS, strengthWeight: weight },
      });
    }
  });

  it("parses whole iteration and seed values", () => {
    expect(
      parseControls(
        controls({ iterations: "1", strengthWeight: "0.5", seed: "42" }),
        ADMIN_MAX_ITERATIONS,
      ),
    ).toEqual({
      ok: true,
      request: { iterations: 1, strengthWeight: "0.5", seed: 42 },
    });
  });

  it("rejects an empty, non-decimal, or non-finite weight", () => {
    for (const weight of ["", "   ", "abc", "0x10", "0b10", "Infinity"]) {
      const parsed = parseControls(controls({ strengthWeight: weight }), MEMBER_MAX_ITERATIONS);
      expect(parsed.ok).toBe(false);
    }
  });

  it("rejects a weight outside 0..10", () => {
    for (const weight of ["-0.1", "10.1", "Infinity", "-Infinity", "NaN"]) {
      const parsed = parseControls(controls({ strengthWeight: weight }), MEMBER_MAX_ITERATIONS);
      expect(parsed.ok).toBe(false);
    }
  });

  it("matches the backend's 18-decimal weight bound", () => {
    expect(
      parseControls(controls({ strengthWeight: "0.123456789012345678" }), MEMBER_MAX_ITERATIONS).ok,
    ).toBe(true);
    // Trailing zeros normalize away, so they do not consume the bound.
    expect(
      parseControls(controls({ strengthWeight: "1.0000000000000000000" }), MEMBER_MAX_ITERATIONS)
        .ok,
    ).toBe(true);
    for (const weight of ["0.1234567890123456789", "1e-19", ".0000000000000000001"]) {
      expect(parseControls(controls({ strengthWeight: weight }), MEMBER_MAX_ITERATIONS).ok).toBe(
        false,
      );
    }
  });

  it("rejects iterations outside the role cap", () => {
    for (const iterations of ["0", "10001", "abc", "1.5", ""]) {
      const parsed = parseControls(controls({ iterations }), MEMBER_MAX_ITERATIONS);
      expect(parsed.ok).toBe(false);
    }
    const admin = parseControls(controls({ iterations: "100000" }), ADMIN_MAX_ITERATIONS);
    expect(admin.ok).toBe(true);
  });

  it("rejects an invalid seed", () => {
    for (const seed of ["-1", "abc", "2147483648", "1.5"]) {
      const parsed = parseControls(controls({ seed }), MEMBER_MAX_ITERATIONS);
      expect(parsed.ok).toBe(false);
    }
    const max = parseControls(controls({ seed: String(MAX_SEED) }), MEMBER_MAX_ITERATIONS);
    expect(max.ok).toBe(true);
  });
});
