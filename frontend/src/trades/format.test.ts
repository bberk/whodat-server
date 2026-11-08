import { describe, expect, it } from "vitest";

import {
  dollarBadgeClass,
  dollarTone,
  dollarToneClass,
  formatAuctionDollars,
  formatTradeDate,
} from "./format";

describe("formatAuctionDollars", () => {
  it("formats positive amounts without sign by default", () => {
    expect(formatAuctionDollars("200.00")).toBe("$200.00");
    expect(formatAuctionDollars("200")).toBe("$200.00");
    expect(formatAuctionDollars(150.5)).toBe("$150.50");
  });

  it("formats positive amounts with plus sign when requested", () => {
    expect(formatAuctionDollars("5.00", { showPlus: true })).toBe("+$5.00");
    expect(formatAuctionDollars(10, { showPlus: true })).toBe("+$10.00");
  });

  it("formats negative amounts with minus sign before dollar symbol", () => {
    expect(formatAuctionDollars("-5.00")).toBe("-$5.00");
    expect(formatAuctionDollars("-10.50", { showPlus: true })).toBe("-$10.50");
    expect(formatAuctionDollars(-25)).toBe("-$25.00");
  });

  it("formats zero amounts neutrally", () => {
    expect(formatAuctionDollars("0.00")).toBe("$0.00");
    expect(formatAuctionDollars("-0.00")).toBe("$0.00");
    expect(formatAuctionDollars(0, { showPlus: true })).toBe("$0.00");
  });
});

describe("dollarTone", () => {
  it("returns pos for numbers > 0", () => {
    expect(dollarTone("5.00")).toBe("pos");
    expect(dollarTone(10)).toBe("pos");
  });

  it("returns neg for numbers < 0", () => {
    expect(dollarTone("-5.00")).toBe("neg");
    expect(dollarTone(-10)).toBe("neg");
  });

  it("returns zero for 0", () => {
    expect(dollarTone("0.00")).toBe("zero");
    expect(dollarTone(0)).toBe("zero");
  });
});

describe("dollarToneClass and dollarBadgeClass", () => {
  it("provides distinct styling classes per tone", () => {
    expect(dollarToneClass("pos")).toContain("text-brand-ink");
    expect(dollarToneClass("neg")).toContain("text-danger-ink");
    expect(dollarToneClass("zero")).toContain("text-ink-muted");

    expect(dollarBadgeClass("pos")).toContain("bg-brand-soft");
    expect(dollarBadgeClass("neg")).toContain("bg-danger-surface");
    expect(dollarBadgeClass("zero")).toContain("bg-surface-strong");
  });
});

describe("formatTradeDate", () => {
  it("formats ISO timestamps deterministically in UTC", () => {
    expect(formatTradeDate("2026-11-07T16:00:00Z")).toBe("Nov 7, 2026");
    expect(formatTradeDate("2027-01-01T00:00:00Z")).toBe("Jan 1, 2027");
  });

  it("returns raw string if invalid date", () => {
    expect(formatTradeDate("not-a-date")).toBe("not-a-date");
  });
});
