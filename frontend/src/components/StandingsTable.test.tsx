import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriesIndexByTeamId } from "../standings/model";
import { historyResponse, standingsResponse } from "../test/fixtures";
import { StandingsTable } from "./StandingsTable";

const rows = standingsResponse.overall;
const weeks = historyResponse.weeks;
const styles = seriesIndexByTeamId(historyResponse);

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
    expect(screen.getByText("495.00")).toBeInTheDocument();
    expect(screen.getByText("10.83")).toBeInTheDocument();
  });

  it("omits every weekly column for a division table", () => {
    renderTable({
      weeks: [],
      caption: "East division standings, 2026.",
      ariaLabel: "East division standings, scrollable horizontally",
    });
    expect(screen.queryByRole("columnheader", { name: /Week \d+ VP/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /^W\d+$/ })).not.toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toHaveLength(6);
    expect(
      screen.getByRole("region", {
        name: "East division standings, scrollable horizontally",
      }),
    ).toBeInTheDocument();
  });

  it("no longer prints a sideways-scroll hint under the table", () => {
    renderTable();
    expect(screen.queryByText(/Table scrolls sideways/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/stay pinned/i)).not.toBeInTheDocument();
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

  it("shows the clinch designation beside the team without changing the team button name", () => {
    renderTable();
    expect(screen.getAllByRole("button", { name: "Alpha" })[0]).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Z — top seed" })).toHaveLength(1);
    expect(screen.getAllByRole("img", { name: "X — clinched playoff berth" })).toHaveLength(2);
  });

  it("omits the designation badge for a team with no proven status", () => {
    renderTable({ rows: [{ ...rows[0], clinch: null }] });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
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

  it("renders an em dash when the API reports no owner", () => {
    renderTable();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders provider-supplied HTML as literal text, not markup", () => {
    const hostileTeam = "<script>alert(1)</script>";
    const hostileOwner = '<img src=x onerror="alert(1)">';
    const { container } = renderTable({
      rows: [{ ...rows[0], team_name: hostileTeam, owner_name: hostileOwner }],
    });

    expect(screen.getByText(hostileTeam)).toBeInTheDocument();
    expect(screen.getByText(hostileOwner)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).toContain("&lt;script&gt;");
  });

  it("sorts by season VP while keeping every API rank value unchanged", async () => {
    const user = userEvent.setup();
    renderTable();
    const vpHeader = screen.getByRole("columnheader", { name: "Season VP" });
    expect(vpHeader).toHaveAttribute("aria-sort", "none");
    expect(screen.getByRole("columnheader", { name: "Team" })).not.toHaveAttribute("aria-sort");
    expect(screen.getByRole("columnheader", { name: "Owner" })).not.toHaveAttribute("aria-sort");

    await user.click(screen.getByRole("button", { name: "Sort by Season VP" }));
    expect(vpHeader).toHaveAttribute("aria-sort", "descending");
    expect(dataRows()[0]).toHaveTextContent("Alpha");
    expect(within(dataRows()[0]).getByRole("rowheader")).toHaveTextContent("1");

    await user.click(screen.getByRole("button", { name: "Sort by Season VP" }));
    expect(vpHeader).toHaveAttribute("aria-sort", "ascending");
    // Foxtrot has the lowest VP (-3.5); its rank stays the API's overall rank of 6.
    expect(dataRows()[0]).toHaveTextContent("Foxtrot");
    expect(within(dataRows()[0]).getByRole("rowheader")).toHaveTextContent("6");
  });

  it("sorts by weekly VP and keeps ties in API order", async () => {
    const user = userEvent.setup();
    renderTable();
    const weekHeader = screen.getByRole("columnheader", { name: "Week 1 VP" });
    await user.click(screen.getByRole("button", { name: "Sort by week 1 VP" }));
    expect(weekHeader).toHaveAttribute("aria-sort", "descending");
    // Alpha and Bravo both scored 2.5; the API order (rank 1, then 2) decides the tie.
    expect(
      dataRows()
        .slice(0, 2)
        .map((row) => row.textContent),
    ).toEqual([expect.stringContaining("Alpha"), expect.stringContaining("Bravo")]);
    await user.click(screen.getByRole("button", { name: "Sort by week 1 VP" }));
    expect(weekHeader).toHaveAttribute("aria-sort", "ascending");
    expect(dataRows()[0]).toHaveTextContent("Foxtrot");
  });

  it("sorts by points for and the record", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(screen.getByRole("button", { name: "Sort by Points for" }));
    expect(screen.getByRole("columnheader", { name: "Points for" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(dataRows()[0]).toHaveTextContent("Alpha");

    await user.click(screen.getByRole("button", { name: "Sort by W-L" }));
    expect(screen.getByRole("columnheader", { name: "W-L" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    // Alpha and Bravo both went 4-0; their API rank order is preserved.
    expect(dataRows()[0]).toHaveTextContent("Alpha");
    expect(dataRows()[1]).toHaveTextContent("Bravo");
  });
});

/** The body rows in render order, excluding the header row. */
function dataRows(): HTMLElement[] {
  const table = screen.getByRole("table");
  return within(table).getAllByRole("row").slice(1);
}
