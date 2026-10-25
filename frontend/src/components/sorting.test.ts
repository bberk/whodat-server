import { describe, expect, it } from "vitest";

import { ariaSortFor, sortRows, toggleSort, type SortState } from "./sorting";

interface Row {
  id: string;
  value: number | null;
}

const rows: Row[] = [
  { id: "a", value: 2 },
  { id: "b", value: 5 },
  { id: "c", value: 2 },
  { id: "d", value: null },
];

function sortedIds(state: SortState | null): string[] {
  return sortRows(rows, state, (row) => row.value).map((row) => row.id);
}

describe("toggleSort", () => {
  it("uses the column's initial direction on the first click and toggles on repeat", () => {
    const first = toggleSort(null, "vp", "desc");
    expect(first).toEqual({ key: "vp", direction: "desc" });
    expect(toggleSort(first, "vp", "desc")).toEqual({ key: "vp", direction: "asc" });
    expect(toggleSort(toggleSort(first, "vp", "desc"), "vp", "desc")).toEqual({
      key: "vp",
      direction: "desc",
    });
  });

  it("switches columns using that column's initial direction", () => {
    const vp: SortState = { key: "vp", direction: "asc" };
    expect(toggleSort(vp, "season", "asc")).toEqual({ key: "season", direction: "asc" });
    expect(toggleSort(vp, "refreshed", "desc")).toEqual({ key: "refreshed", direction: "desc" });
  });
});

describe("sortRows", () => {
  it("keeps API order when no column is sorted", () => {
    expect(sortedIds(null)).toEqual(["a", "b", "c", "d"]);
  });

  it("sorts numerically in both directions with stable ties", () => {
    expect(sortedIds({ key: "value", direction: "asc" })).toEqual(["a", "c", "b", "d"]);
    expect(sortedIds({ key: "value", direction: "desc" })).toEqual(["b", "a", "c", "d"]);
  });

  it("keeps missing values last in both directions", () => {
    expect(sortedIds({ key: "value", direction: "asc" }).at(-1)).toBe("d");
    expect(sortedIds({ key: "value", direction: "desc" }).at(-1)).toBe("d");
  });

  it("compares string values and sorts empty and missing values last", () => {
    const mixed: { id: string; value: string | null }[] = [
      { id: "a", value: "beta" },
      { id: "b", value: null },
      { id: "c", value: "alpha" },
      { id: "d", value: "" },
    ];
    const asc = sortRows(mixed, { key: "value", direction: "asc" }, (row) => row.value);
    const desc = sortRows(mixed, { key: "value", direction: "desc" }, (row) => row.value);
    expect(asc.map((row) => row.id)).toEqual(["c", "a", "b", "d"]);
    expect(desc.map((row) => row.id)).toEqual(["a", "c", "b", "d"]);
  });

  it("passes the sort key to the value accessor for dynamic columns", () => {
    const weekly = [
      { id: "a", week1: 1, week2: 3 },
      { id: "b", week1: 2, week2: 1 },
    ];
    const sorted = sortRows(weekly, { key: "week2", direction: "desc" }, (row, key) =>
      key === "week2" ? row.week2 : null,
    );
    expect(sorted.map((row) => row.id)).toEqual(["a", "b"]);
  });
});

describe("ariaSortFor", () => {
  it("reports ascending, descending, and none", () => {
    expect(ariaSortFor({ key: "vp", direction: "asc" }, "vp")).toBe("ascending");
    expect(ariaSortFor({ key: "vp", direction: "desc" }, "vp")).toBe("descending");
    expect(ariaSortFor({ key: "vp", direction: "desc" }, "pf")).toBe("none");
    expect(ariaSortFor(null, "vp")).toBe("none");
  });
});
