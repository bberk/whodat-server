import { describe, expect, it } from "vitest";

import { historyResponse, standingsResponse } from "../test/fixtures";
import { weeklyBreakdownFor } from "./model";

describe("weeklyBreakdownFor", () => {
  it("returns no rows for a week the API did not include", () => {
    expect(weeklyBreakdownFor(historyResponse, standingsResponse.overall, 99)).toEqual({
      rows: [],
      note: null,
    });
  });

  it("orders equal weekly VP by overall rank", () => {
    const rows = weeklyBreakdownFor(historyResponse, standingsResponse.overall, 4).rows;
    expect(rows.slice(0, 3).map((row) => row.teamName)).toEqual(["Alpha", "Bravo", "Echo"]);
  });

  it("fills missing weekly, cumulative, and rank values with zero", () => {
    const rows = weeklyBreakdownFor(
      {
        weeks: [1, 2],
        teams: [{ team_id: 99, team_name: "Sparse", weekly: ["1"], cumulative: [] }],
      },
      [],
      2,
    ).rows;
    expect(rows).toEqual([
      {
        teamId: 99,
        teamName: "Sparse",
        styleIndex: 0,
        weekly: "0",
        cumulative: "0",
        overallRank: 0,
      },
    ]);
  });
});
