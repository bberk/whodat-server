import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockStandingsBundle, seriesIndexByTeamId } from "../mocks/standings";
import { StandingsTable } from "./StandingsTable";

const rows = mockStandingsBundle.standings.overall;
const weeks = mockStandingsBundle.history.weeks;
const styles = seriesIndexByTeamId(mockStandingsBundle);

function renderTable(overrides: Partial<Parameters<typeof StandingsTable>[0]> = {}) {
  return render(
    <StandingsTable
      caption="Overall 2026 standings."
      ariaLabel="Overall standings"
      rows={rows}
      weeks={weeks}
      showTies={false}
      selectedTeamId={null}
      onSelectTeam={() => {}}
      seriesIndexByTeamId={styles}
      {...overrides}
    />,
  );
}

describe("StandingsTable", () => {
  it("renders rank, team, owner, season VP, record, points for, and a column per week", () => {
    renderTable();
    for (const header of ["#", "Team", "Owner", "Season VP", "W-L", "Points for"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(screen.getByRole("columnheader", { name: "Week 1 VP" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Week 4 VP" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "1" })).toBeInTheDocument();
    expect(screen.getAllByText("495.00")).toHaveLength(1);
    expect(screen.getByText("10.83")).toBeInTheDocument();
  });

  it("scrolls inside its own labelled region so the page body does not scroll", () => {
    renderTable();
    const region = screen.getByRole("region", { name: "Overall standings" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.className).toContain("overflow-x-auto");
  });

  it("shows W-L-T when the season has an H2H tie", () => {
    const tied = [{ ...rows[0], wins: 3, losses: 1, ties: 1 }];
    renderTable({ rows: tied, showTies: true });
    expect(screen.getByRole("columnheader", { name: "W-L-T" })).toBeInTheDocument();
    expect(screen.getByText("3-1-1")).toBeInTheDocument();
  });

  it("renders negative VP with a minus sign and no + prefix anywhere", () => {
    const { container } = renderTable();
    const cells = Array.from(container.querySelectorAll("td"));
    expect(cells.some((cell) => cell.textContent === "-0.5")).toBe(true);
    expect(cells.some((cell) => cell.textContent?.startsWith("+") ?? false)).toBe(false);
  });

  it("renders the rank supplied by the data layer without re-ranking", () => {
    const divisionRows = [
      { ...rows[0], rank: 1 },
      { ...rows[3], rank: 4 },
      { ...rows[5], rank: 6 },
    ];
    renderTable({
      rows: divisionRows,
      caption: "West division standings, 2026.",
      ariaLabel: "West division standings, scrollable horizontally",
    });
    const ranks = screen.getAllByRole("rowheader").map((cell) => cell.textContent);
    expect(ranks).toEqual(["1", "4", "6"]);
  });

  it("selects a team through a keyboard-operable button", async () => {
    const onSelectTeam = vi.fn();
    const user = userEvent.setup();
    renderTable({ onSelectTeam });
    const alpha = screen.getAllByRole("button", { name: "Alpha" })[0];
    expect(alpha).toHaveAttribute("aria-pressed", "false");
    await user.click(alpha);
    expect(onSelectTeam).toHaveBeenCalledWith(7);
  });

  it("marks the selected team with aria-pressed", () => {
    renderTable({ selectedTeamId: 7 });
    expect(screen.getAllByRole("button", { name: "Alpha" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
