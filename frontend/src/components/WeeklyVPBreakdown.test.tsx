import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { weeklyBreakdownFor } from "../standings/model";
import { historyResponse, standingsResponse } from "../test/fixtures";
import { WeeklyVPBreakdown } from "./WeeklyVPBreakdown";

const weeks = historyResponse.weeks;
const week4 = weeklyBreakdownFor(historyResponse, standingsResponse.overall, 4);

describe("WeeklyVPBreakdown", () => {
  it("renders the week's VP and cumulative VP from the API values", () => {
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
    for (const header of ["Team", "Weekly VP", "Cumulative VP"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    const table = screen.getByRole("table", { name: /week 4 victory points per team/i });
    const bodyRows = within(table).getAllByRole("row").slice(1);
    // ordered by that week's VP: the three 2.33 rows come first
    expect(within(bodyRows[0]).getByRole("rowheader")).toHaveTextContent("Alpha");
    expect(within(bodyRows[2]).getByRole("rowheader")).toHaveTextContent("Echo");
    expect(within(bodyRows[5]).getByRole("rowheader")).toHaveTextContent("Foxtrot");
    expect(within(bodyRows[0]).getByText("10.83")).toBeInTheDocument();
  });

  it("keeps negative weekly VP and shows the cumulative total through the week", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={3}
        onSelectWeek={() => {}}
        rows={weeklyBreakdownFor(historyResponse, standingsResponse.overall, 3).rows}
        note={null}
        selectedTeamId={null}
      />,
    );
    expect(screen.getAllByText("-0.5").length).toBeGreaterThan(0);
    expect(screen.getByText("-2.5")).toBeInTheDocument();
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
        note={null}
        selectedTeamId={null}
      />,
    );
    expect(screen.getByRole("button", { name: "W4" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "W1" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "W1" }));
    expect(onSelectWeek).toHaveBeenCalledWith(1);
  });

  it("shows a callout note when the data layer supplies one", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={1}
        onSelectWeek={() => {}}
        rows={weeklyBreakdownFor(historyResponse, standingsResponse.overall, 1).rows}
        note="Cumulative VP is through week 1."
        selectedTeamId={null}
      />,
    );
    expect(screen.getByText("Cumulative VP is through week 1.")).toBeInTheDocument();
  });

  it("renders no callout when the note is absent", () => {
    render(
      <WeeklyVPBreakdown
        weeks={weeks}
        selectedWeek={2}
        onSelectWeek={() => {}}
        rows={weeklyBreakdownFor(historyResponse, standingsResponse.overall, 2).rows}
        note={null}
        selectedTeamId={null}
      />,
    );
    expect(screen.queryByText(/cumulative vp is through/i)).not.toBeInTheDocument();
  });
});
