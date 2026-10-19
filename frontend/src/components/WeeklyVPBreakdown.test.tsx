import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockStandingsBundle, weeklyBreakdownFor } from "../mocks/standings";
import { WeeklyVPBreakdown } from "./WeeklyVPBreakdown";

const weeks = mockStandingsBundle.history.weeks;
const week4 = weeklyBreakdownFor(mockStandingsBundle, 4);

describe("WeeklyVPBreakdown", () => {
  it("renders the component columns and the week's totals", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={4}
        onSelectWeek={() => {}}
        rows={week4.rows}
        note={week4.note}
        selectedTeamId={null}
      />,
    );
    for (const header of ["H2H", "Top half", "High score", "Low score", "Total VP"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    const table = screen.getByRole("table", { name: /week 4 victory point components/i });
    const bodyRows = within(table).getAllByRole("row").slice(1);
    // ordered by that week's total VP: the three 2.33 rows come first
    expect(within(bodyRows[0]).getByRole("rowheader")).toHaveTextContent("Alpha");
    expect(within(bodyRows[3]).getByRole("rowheader")).toHaveTextContent("Charlie");
    expect(within(bodyRows[5]).getByRole("rowheader")).toHaveTextContent("Foxtrot");
  });

  it("shows the high-score split as 0.33 without rounding it away", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={4}
        onSelectWeek={() => {}}
        rows={week4.rows}
        note={null}
        selectedTeamId={null}
      />,
    );
    expect(screen.getAllByText("0.33")).toHaveLength(3);
  });

  it("marks the active week and reports selection changes", async () => {
    const onSelectWeek = vi.fn();
    const user = userEvent.setup();
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={4}
        onSelectWeek={onSelectWeek}
        rows={week4.rows}
        note={week4.note}
        selectedTeamId={null}
      />,
    );
    expect(screen.getByRole("button", { name: "W4" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "W1" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "W1" }));
    expect(onSelectWeek).toHaveBeenCalledWith(1);
  });

  it("shows the callout note when there is one", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={1}
        onSelectWeek={() => {}}
        rows={weeklyBreakdownFor(mockStandingsBundle, 1).rows}
        note={weeklyBreakdownFor(mockStandingsBundle, 1).note}
        selectedTeamId={null}
      />,
    );
    expect(screen.getByText(/example A/i)).toBeInTheDocument();
  });

  it("renders no callout when the note is absent", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={2}
        onSelectWeek={() => {}}
        rows={weeklyBreakdownFor(mockStandingsBundle, 2).rows}
        note={null}
        selectedTeamId={null}
      />,
    );
    expect(screen.queryByText(/ACCEPTANCE.md/i)).not.toBeInTheDocument();
  });
});
