import { describe, expect, it } from "vitest";

import { SERIES_STYLES, seriesStyle } from "./series";

describe("seriesStyle", () => {
  it("pairs every preset color with a dash pattern and a marker shape", () => {
    expect(SERIES_STYLES.length).toBeGreaterThanOrEqual(6);
    for (const style of SERIES_STYLES) {
      expect(style.color).toMatch(/^var\(--series-\d+\)$/);
      expect(style.marker).toBeTruthy();
    }
  });

  it("uses a distinct palette variable for every preset", () => {
    expect(new Set(SERIES_STYLES.map((style) => style.color)).size).toBe(SERIES_STYLES.length);
  });

  it("distinguishes the first six series by marker shape", () => {
    const markers = SERIES_STYLES.slice(0, 6).map((style) => style.marker);
    expect(new Set(markers).size).toBe(6);
  });

  it("wraps around for leagues larger than the preset list", () => {
    expect(seriesStyle(SERIES_STYLES.length)).toEqual(SERIES_STYLES[0]);
  });
});
