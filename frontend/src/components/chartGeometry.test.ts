import { describe, expect, it } from "vitest";

import { niceScale, positionFor, spreadLabelPositions } from "./chartGeometry";

describe("niceScale", () => {
  it("keeps zero in range and rounds to a readable step", () => {
    expect(niceScale(-3.5, 10.83, 4)).toEqual({
      min: -5,
      max: 15,
      ticks: [-5, 0, 5, 10, 15],
    });
  });

  it("uses a step of 1, 2, 2.5, 5, or 10 depending on the span", () => {
    expect(niceScale(0, 4, 4).ticks).toEqual([0, 1, 2, 3, 4]);
    expect(niceScale(0, 8, 4).ticks).toEqual([0, 2, 4, 6, 8]);
    expect(niceScale(0, 10, 4).ticks).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(niceScale(0, 20, 4).ticks).toEqual([0, 5, 10, 15, 20]);
    expect(niceScale(0, 24, 4)).toEqual({ min: 0, max: 30, ticks: [0, 10, 20, 30] });
  });

  it("always spans zero even for a negative-only range", () => {
    expect(niceScale(-4, 0, 4)).toEqual({ min: -4, max: 0, ticks: [-4, -3, -2, -1, 0] });
  });

  it("falls back to a unit scale when every value is zero", () => {
    expect(niceScale(0, 0)).toEqual({ min: -1, max: 1, ticks: [-1, 0, 1] });
  });
});

describe("positionFor", () => {
  it("spans the plot and centres a single point", () => {
    expect(positionFor(0, 4, 44, 580)).toBe(44);
    expect(positionFor(3, 4, 44, 580)).toBe(624);
    expect(positionFor(0, 1, 34, 326)).toBe(197);
  });
});

describe("spreadLabelPositions", () => {
  it("pushes overlapping labels apart", () => {
    expect(spreadLabelPositions([100, 102, 104], 16, 0, 1000)).toEqual([100, 116, 132]);
  });

  it("keeps the labels inside the bottom bound", () => {
    expect(spreadLabelPositions([100, 102, 104], 16, 0, 120)).toEqual([88, 104, 120]);
  });

  it("preserves the original order of the input", () => {
    expect(spreadLabelPositions([104, 100, 102], 16, 0, 1000)).toEqual([132, 100, 116]);
  });
});
