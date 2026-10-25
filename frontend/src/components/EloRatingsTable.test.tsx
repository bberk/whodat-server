import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { eloHistoryResponse } from "../test/fixtures";
import { EloRatingsTable, type EloRatingsTableProps } from "./EloRatingsTable";

function renderTable(overrides: Partial<EloRatingsTableProps> = {}) {
  return render(
    <EloRatingsTable
      teams={eloHistoryResponse.teams}
      selectedTeamKey={null}
      onSelectTeam={() => {}}
      {...overrides}
    />,
  );
}

function rows(): HTMLElement[] {
  const table = screen.getByRole("table");
  return within(table).getAllByRole("row").slice(1);
}

describe("EloRatingsTable", () => {
  it("renders current scores highest first with the stable current-score rank", () => {
    renderTable();
    expect(rows()).toHaveLength(3);
    expect(within(rows()[0]).getByRole("rowheader")).toHaveTextContent("1");
    expect(within(rows()[0]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(within(rows()[1]).getByRole("button", { name: "Charlie" })).toBeInTheDocument();
    expect(within(rows()[2]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();
  });

  it("sorts numeric columns ascending and descending and never text columns", async () => {
    const user = userEvent.setup();
    renderTable();

    for (const header of ["#", "Team", "Owner"]) {
      expect(screen.getByRole("columnheader", { name: header })).not.toHaveAttribute("aria-sort");
    }
    for (const header of ["Elo score", "Last week", "This season", "Peak", "Low"]) {
      expect(screen.getByRole("columnheader", { name: header })).toHaveAttribute(
        "aria-sort",
        "none",
      );
    }

    const eloHeader = screen.getByRole("columnheader", { name: "Elo score" });
    await user.click(screen.getByRole("button", { name: "Sort by Elo score" }));
    expect(eloHeader).toHaveAttribute("aria-sort", "descending");
    expect(within(rows()[0]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sort by Elo score" }));
    expect(eloHeader).toHaveAttribute("aria-sort", "ascending");
    expect(within(rows()[0]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();

    const lastWeek = screen.getByRole("columnheader", { name: "Last week" });
    await user.click(screen.getByRole("button", { name: "Sort by Last week" }));
    expect(lastWeek).toHaveAttribute("aria-sort", "descending");
    // Alpha and Charlie both moved +12.6; API/current order breaks the tie.
    expect(within(rows()[0]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(within(rows()[1]).getByRole("button", { name: "Charlie" })).toBeInTheDocument();
    expect(within(rows()[2]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();

    const thisSeason = screen.getByRole("columnheader", { name: "This season" });
    await user.click(screen.getByRole("button", { name: "Sort by This season" }));
    expect(thisSeason).toHaveAttribute("aria-sort", "descending");
    expect(within(rows()[0]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(within(rows()[2]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();
  });

  it("keeps the current-score rank when the table is sorted by peak or low", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Sort by Peak" }));
    expect(screen.getByRole("columnheader", { name: "Peak" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(within(rows()[0]).getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(within(rows()[0]).getByRole("rowheader")).toHaveTextContent("1");

    await user.click(screen.getByRole("button", { name: "Sort by Peak" }));
    expect(within(rows()[0]).getByRole("button", { name: "Bravo" })).toBeInTheDocument();
    // Bravo is #3 by current score even though it is first in this peak ordering.
    expect(within(rows()[0]).getByRole("rowheader")).toHaveTextContent("3");

    await user.click(screen.getByRole("button", { name: "Sort by Low" }));
    expect(screen.getByRole("columnheader", { name: "Low" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(within(rows()[0]).getByRole("rowheader")).toHaveTextContent("1");
  });

  it("selects a team through the row button", async () => {
    const onSelectTeam = vi.fn();
    const user = userEvent.setup();
    renderTable({ onSelectTeam, selectedTeamKey: "espn:2" });
    const bravo = within(rows()[2]).getByRole("button", { name: "Bravo" });
    expect(bravo).toHaveAttribute("aria-pressed", "true");
    await user.click(bravo);
    expect(onSelectTeam).toHaveBeenCalledWith("espn:2");
  });
});
