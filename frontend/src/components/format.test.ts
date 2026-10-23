import { describe, expect, it } from "vitest";

import {
  formatEloChange,
  formatEloValue,
  formatEloWhole,
  formatPoints,
  formatRecord,
  formatVP,
  toNumber,
  vpTone,
  vpToneClass,
} from "./format";

describe("formatVP", () => {
  it("trims trailing zeros and keeps exact decimals", () => {
    expect(formatVP("2.50")).toBe("2.5");
    expect(formatVP("3.00")).toBe("3");
    expect(formatVP("10.83")).toBe("10.83");
    expect(formatVP("0.33")).toBe("0.33");
  });

  it("never prefixes a positive value with +", () => {
    expect(formatVP("2.5").startsWith("+")).toBe(false);
    expect(formatVP("0.5")).toBe("0.5");
  });

  it("keeps - for negative VP and renders zero plainly", () => {
    expect(formatVP("-0.50")).toBe("-0.5");
    expect(formatVP("-1")).toBe("-1");
    expect(formatVP("0.00")).toBe("0");
    expect(formatVP("-0.00")).toBe("0");
  });

  it("normalizes stray leading zeros", () => {
    expect(formatVP("007")).toBe("7");
    expect(formatVP(".5")).toBe("0.5");
  });
});

describe("vpTone", () => {
  it("classifies positive, negative, and zero", () => {
    expect(vpTone("2.5")).toBe("pos");
    expect(vpTone("-1")).toBe("neg");
    expect(vpTone("0.00")).toBe("zero");
  });

  it("maps each tone to a distinct text class", () => {
    expect(vpToneClass("pos")).toBe("text-brand");
    expect(vpToneClass("neg")).toBe("text-red-700");
    expect(vpToneClass("zero")).toBe("text-gray-500");
  });
});

describe("formatPoints", () => {
  it("renders exactly two decimals", () => {
    expect(formatPoints("495.00")).toBe("495.00");
    expect(formatPoints("812.3")).toBe("812.30");
    expect(formatPoints("100")).toBe("100.00");
    expect(formatPoints("-12.3")).toBe("-12.30");
    expect(formatPoints("-7")).toBe("-7.00");
  });
});

describe("formatRecord", () => {
  it("shows W-L when the season has no H2H ties", () => {
    expect(formatRecord({ wins: 4, losses: 2, ties: 0 }, false)).toBe("4-2");
  });

  it("shows W-L-T when the season has an H2H tie", () => {
    expect(formatRecord({ wins: 3, losses: 1, ties: 1 }, true)).toBe("3-1-1");
  });
});

describe("toNumber", () => {
  it("parses decimal strings for geometry", () => {
    expect(toNumber("-3.5")).toBe(-3.5);
  });
});

describe("formatEloWhole", () => {
  it("rounds the current Elo score to the nearest whole number", () => {
    expect(formatEloWhole("1525.2")).toBe("1525");
    expect(formatEloWhole("1525.5")).toBe("1526");
    expect(formatEloWhole("1524.4")).toBe("1524");
    expect(formatEloWhole("-0.4")).toBe("0");
  });
});

describe("formatEloValue", () => {
  it("keeps exactly two decimals for chart and peak/low values", () => {
    expect(formatEloValue("1525.2")).toBe("1525.20");
    expect(formatEloValue("1500")).toBe("1500.00");
    expect(formatEloValue("-0.005")).toBe("-0.01");
    expect(formatEloValue("-0.001")).toBe("0.00");
  });
});

describe("formatEloChange", () => {
  it("uses two decimals and an explicit plus sign for gains", () => {
    expect(formatEloChange("12.6")).toBe("+12.60");
    expect(formatEloChange("-12.6")).toBe("-12.60");
    expect(formatEloChange("0")).toBe("0.00");
    expect(formatEloChange("-0.001")).toBe("0.00");
  });
});
