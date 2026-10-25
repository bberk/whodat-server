import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EloWeek } from "../api/types";
import { EloChart, type EloChartProps, type EloChartSeries } from "./EloChart";

const WEEKS: EloWeek[] = [
  { index: 0, season: 2025, week: 1, is_cup_week: false, is_season_start: true, rated: true },
  { index: 1, season: 2025, week: 2, is_cup_week: true, is_season_start: false, rated: false },
  { index: 2, season: 2026, week: 1, is_cup_week: false, is_season_start: true, rated: true },
];

const SERIES: EloChartSeries[] = [
  {
    teamKey: "a",
    name: "Alpha",
    ownerName: "Alex",
    styleIndex: 0,
    values: ["1500", "1500", "1512"],
    current: "1512",
  },
  {
    teamKey: "b",
    name: "Bravo",
    ownerName: null,
    styleIndex: 1,
    values: [null, "1488", "1476"],
    current: "1476",
  },
  {
    teamKey: "c",
    name: "Charlie",
    ownerName: null,
    styleIndex: 2,
    values: [null, null, null],
    current: "1500",
  },
];

function chartProps(overrides: Partial<EloChartProps> = {}): EloChartProps {
  return {
    weeks: WEEKS,
    series: SERIES,
    boundaries: [{ season: 2026, week_index: 2 }],
    mode: "actual_schedule",
    startingRating: "1500",
    visibleTeamKeys: ["a", "b", "c"],
    selectedTeamKey: null,
    onToggleTeam: vi.fn(),
    onIsolateTeam: vi.fn(),
    onSelectTeam: vi.fn(),
    compact: false,
    ...overrides,
  };
}

describe("EloChart", () => {
  it("renders the empty placeholder when there is nothing to plot", () => {
    render(<EloChart {...chartProps({ weeks: [], series: [] })} />);

    expect(screen.getByText("No rated weeks yet.")).toBeInTheDocument();
  });

  it("renders compact geometry, cup markers, and the actual-schedule summary", () => {
    const { container } = render(
      <EloChart {...chartProps({ compact: true, selectedTeamKey: "a" })} />,
    );

    const chart = screen.getByRole("img", { name: /Actual schedule/i });
    expect(chart.getAttribute("aria-label")).toContain("Cup weeks are marked and skipped");
    expect(container.querySelector('[data-cup-week="2025-2"]')).toBeInTheDocument();
    expect(container.querySelector('[data-team-key="a"]')).toHaveAttribute("stroke-width", "3.4");
    expect(screen.queryByText("Week", { exact: true })).not.toBeInTheDocument();
  });

  it("handles a view with every series hidden and a team with no data", () => {
    render(<EloChart {...chartProps({ visibleTeamKeys: [] })} />);

    expect(screen.getByRole("img").getAttribute("aria-label")).toContain(
      "No visible team has a rating yet.",
    );
    expect(screen.getAllByText("Charlie")[0]).toBeInTheDocument();
  });

  it("omits the cup note when the range has no cup week", () => {
    const weeks = WEEKS.filter((week) => !week.is_cup_week);
    render(
      <EloChart
        {...chartProps({
          weeks,
          mode: "round_robin",
          boundaries: [{ season: 2026, week_index: 1 }],
        })}
      />,
    );

    const label = screen.getByRole("img", { name: /Round robin/i }).getAttribute("aria-label");
    expect(label).not.toContain("Cup weeks");
  });

  it("isolates one team when its legend chip is double-clicked", async () => {
    const onToggleTeam = vi.fn();
    const onIsolateTeam = vi.fn();
    const user = userEvent.setup();
    render(<EloChart {...chartProps({ onToggleTeam, onIsolateTeam })} />);

    expect(screen.getByText(/Double-click a team to show only that team/)).toBeInTheDocument();
    const chip = screen.getByRole("button", { name: "Show or hide Bravo series" });
    expect(chip.closest("li")?.getAttribute("title")).toContain("Double-click to show only Bravo");

    await user.dblClick(chip);
    expect(onIsolateTeam).toHaveBeenCalledWith("b");
    expect(onToggleTeam).toHaveBeenCalledTimes(2);

    // A single keyboard-operable click still performs the plain toggle.
    onToggleTeam.mockClear();
    await user.click(chip);
    expect(onToggleTeam).toHaveBeenCalledWith("b");
    expect(onIsolateTeam).toHaveBeenCalledTimes(1);
  });
});
