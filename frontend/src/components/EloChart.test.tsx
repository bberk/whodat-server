import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EloWeek } from "../api/types";
import { expectRowDividersAcrossEveryCell } from "../test/tableDividers";
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

const MANY_WEEKS: EloWeek[] = Array.from({ length: 40 }, (_, index) => {
  const week = (index % 20) + 1;
  return {
    index,
    season: index < 20 ? 2024 : 2025,
    week,
    is_cup_week: false,
    is_season_start: week === 1,
    rated: true,
  };
});

const MANY_SERIES: EloChartSeries[] = [
  {
    teamKey: "a",
    name: "Alpha",
    ownerName: "Alex",
    styleIndex: 0,
    values: MANY_WEEKS.map((_, index) => String(1500 + (index % 7))),
    current: "1506",
  },
  {
    teamKey: "b",
    name: "Bravo",
    ownerName: null,
    styleIndex: 1,
    values: MANY_WEEKS.map((_, index) => String(1490 + (index % 5))),
    current: "1494",
  },
];

const SEASON_WEEKS: EloWeek[] = Array.from({ length: 12 }, (_, seasonIndex) =>
  Array.from({ length: 14 }, (_, weekIndex) => {
    const week = weekIndex + 1;
    return {
      index: seasonIndex * 14 + weekIndex,
      season: 2015 + seasonIndex,
      week,
      is_cup_week: week === 13,
      is_season_start: week === 1,
      rated: week !== 13,
    };
  }),
).flat();

const SEASON_BOUNDARIES = Array.from({ length: 12 }, (_, seasonIndex) => ({
  season: 2015 + seasonIndex,
  week_index: seasonIndex * 14,
})).slice(1);

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

function weekLabels(container: HTMLElement): SVGTextElement[] {
  return Array.from(container.querySelectorAll<SVGTextElement>('text[data-axis="week"]'));
}

function gapsBetween(labels: readonly SVGTextElement[]): number[] {
  const xs = labels.map((label) => Number(label.getAttribute("x")));
  return xs.slice(1).map((x, index) => x - xs[index]);
}

describe("EloChart", () => {
  it("renders the empty placeholder when there is nothing to plot", () => {
    render(<EloChart {...chartProps({ weeks: [], series: [] })} />);

    expect(screen.getByText("No rated weeks yet.")).toBeInTheDocument();
  });

  it("draws a plain dot at every rated week and in the legend with CSS-variable fills", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    // Alpha has three rated weeks and Bravo two, plus one legend dot per series.
    const dots = container.querySelectorAll("[data-dot]");
    expect(dots).toHaveLength(5);
    expect(container.querySelectorAll("svg circle")).toHaveLength(5 + SERIES.length);
    expect(container.querySelectorAll("svg path")).toHaveLength(0);
    expect(dots[0].getAttribute("style")).toContain("var(--series-0)");
    expect(dots[3].getAttribute("style")).toContain("var(--series-1)");
  });

  it("breaks a line into segments around a season with no rating", () => {
    const gapped: EloChartSeries[] = [
      {
        ...MANY_SERIES[0],
        values: MANY_WEEKS.map((_, index) => (index === 20 ? null : String(1500 + (index % 5)))),
      },
    ];
    const { container } = render(
      <EloChart {...chartProps({ weeks: MANY_WEEKS, series: gapped })} />,
    );

    expect(container.querySelectorAll('[data-team-key="a"]')).toHaveLength(2);
  });

  it("selects a team from its legend chip", async () => {
    const onSelectTeam = vi.fn();
    const user = userEvent.setup();
    render(<EloChart {...chartProps({ onSelectTeam })} />);

    await user.click(screen.getByRole("button", { name: /Highlight Alpha/ }));
    expect(onSelectTeam).toHaveBeenCalledWith("a");
  });

  it("renders compact geometry and the actual-schedule summary without cup markers", () => {
    const { container } = render(
      <EloChart {...chartProps({ compact: true, selectedTeamKey: "a" })} />,
    );

    const chart = screen.getByRole("img", { name: /Actual schedule/i });
    expect(chart.getAttribute("aria-label")).not.toMatch(/Cup/i);
    expect(container.querySelector("[data-cup-week]")).toBeNull();
    expect(container.querySelector('[data-team-key="a"]')).toHaveAttribute("stroke-width", "3.4");
    expect(screen.queryByText("Week", { exact: true })).not.toBeInTheDocument();
  });

  it("omits cup markers and cup-specific chart text", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    expect(container.querySelector("[data-cup-week]")).toBeNull();
    expect(container.querySelector('svg[role="img"]')?.textContent).not.toMatch(/Cup/i);
    expect(screen.getByRole("img").getAttribute("aria-label")).not.toMatch(/Cup/i);
  });

  it("does not repeat team names or values at the end of the lines", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    const svgText = Array.from(
      container.querySelectorAll("svg text"),
      (element) => element.textContent ?? "",
    );
    expect(svgText.some((text) => text.includes("Alpha"))).toBe(false);
    expect(svgText.some((text) => text.includes("Bravo"))).toBe(false);
    expect(svgText.some((text) => text.includes("1512.00"))).toBe(false);
  });

  it("keeps the data table's exact values without cup annotations", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    expect(screen.queryByText(/\(cup\)/)).not.toBeInTheDocument();
    const headers = Array.from(container.querySelectorAll("thead th")).map((header) =>
      header.textContent?.trim(),
    );
    expect(headers).toEqual(["Team", "2025 W1", "2025 W2", "2026 W1"]);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(within(table as HTMLElement).getByText("1512.00")).toBeInTheDocument();
  });

  it("prints whole-number value ticks", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    const values = Array.from(
      container.querySelectorAll('text[data-axis="value"]'),
      (label) => label.textContent ?? "",
    );
    expect(values.length).toBeGreaterThan(1);
    for (const value of values) {
      expect(value).toMatch(/^-?\d+$/);
    }
  });

  it("labels a small, evenly spaced set of weeks and every season boundary", () => {
    const { container } = render(
      <EloChart
        {...chartProps({
          weeks: MANY_WEEKS,
          series: MANY_SERIES,
          boundaries: [{ season: 2025, week_index: 20 }],
        })}
      />,
    );

    const labels = weekLabels(container);
    expect(labels.length).toBeGreaterThanOrEqual(2);
    expect(labels.length).toBeLessThanOrEqual(8);
    expect(Math.min(...gapsBetween(labels))).toBeGreaterThanOrEqual(40);
    expect(labels[0].textContent).toBe("W1");
    expect(labels[labels.length - 1].textContent).toBe("W20");

    const seasons = Array.from(
      container.querySelectorAll('text[data-axis="season"]'),
      (label) => label.textContent,
    );
    expect(seasons).toEqual(["2024", "2025"]);
  });

  it("thins season labels on a compact chart so years never overlap", () => {
    const series: EloChartSeries[] = [
      {
        ...MANY_SERIES[0],
        values: SEASON_WEEKS.map((_, index) => String(1500 + (index % 9))),
      },
    ];
    const { container } = render(
      <EloChart
        {...chartProps({
          compact: true,
          weeks: SEASON_WEEKS,
          series,
          boundaries: SEASON_BOUNDARIES,
        })}
      />,
    );

    const seasons = Array.from(container.querySelectorAll('text[data-axis="season"]'));
    expect(seasons.length).toBeGreaterThan(1);
    expect(seasons.length).toBeLessThanOrEqual(6);
    const xs = seasons.map((label) => Number(label.getAttribute("x")));
    const gaps = xs.slice(1).map((x, index) => x - xs[index]);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(34);
    // Every boundary still has its vertical rule even when its label is thinned out.
    expect(container.querySelectorAll(".stroke-chart-boundary")).toHaveLength(11);
  });

  it("limits compact week ticks so they never overlap", () => {
    const { container } = render(
      <EloChart {...chartProps({ compact: true, weeks: MANY_WEEKS, series: MANY_SERIES })} />,
    );

    const labels = weekLabels(container);
    expect(labels.length).toBeLessThanOrEqual(6);
    expect(Math.min(...gapsBetween(labels))).toBeGreaterThanOrEqual(34);
  });

  it("renders a wrapping chip grid with every team and its current value", () => {
    const { container } = render(<EloChart {...chartProps()} />);

    const legend = screen.getByRole("list", { name: "Chart series toggles" });
    expect(legend).toHaveClass("grid", "grid-cols-1", "sm:grid-cols-2", "xl:grid-cols-3");
    expect(container.querySelectorAll("[data-series-chip]")).toHaveLength(3);
    expect(within(legend).getByText("Alpha")).toHaveClass("break-words");
    expect(within(legend).getByText("1512.00")).toBeInTheDocument();
    expect(within(legend).getByText("1476.00")).toBeInTheDocument();
  });

  it("keeps the selected team emphasised and distinguishes series by dash and colour", () => {
    const { container } = render(<EloChart {...chartProps({ selectedTeamKey: "a" })} />);

    const alpha = container.querySelector('[data-team-key="a"]');
    const bravo = container.querySelector('[data-team-key="b"]');
    expect(alpha).toHaveAttribute("stroke-width", "3.4");
    expect(alpha?.getAttribute("style")).toContain("var(--series-0)");
    expect(alpha).not.toHaveAttribute("stroke-dasharray");
    expect(bravo).toHaveAttribute("stroke-width", "1.8");
    expect(bravo).toHaveAttribute("stroke-dasharray", "8 5");
    expect(bravo).toHaveAttribute("opacity", "0.55");
    expect(container.querySelector('[data-dot="a"]')).toHaveAttribute("r", "2.6");
    expect(container.querySelector('[data-dot="b"]')).toHaveAttribute("r", "1.6");
  });

  it("isolates one series and reports every other chip as hidden", () => {
    const { container } = render(<EloChart {...chartProps({ visibleTeamKeys: ["b"] })} />);

    expect(container.querySelector('[data-team-key="a"]')).not.toBeInTheDocument();
    expect(container.querySelector('[data-team-key="b"]')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show or hide Alpha series" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Show or hide Bravo series" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("handles a view with every series hidden and a team with no data", () => {
    render(<EloChart {...chartProps({ visibleTeamKeys: [] })} />);

    expect(screen.getByRole("img").getAttribute("aria-label")).toContain(
      "No visible team has a rating yet.",
    );
    expect(screen.getAllByText("Charlie")[0]).toBeInTheDocument();
  });

  it("paints the data table's row divider across the final column", () => {
    const { container } = render(<EloChart {...chartProps()} />);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expectRowDividersAcrossEveryCell(table as HTMLElement);
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
