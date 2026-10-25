import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildHistorySeries } from "../standings/model";
import { historyResponse } from "../test/fixtures";
import { VPChart, type ChartSeries, type VPChartProps } from "./VPChart";

const weeks = historyResponse.weeks;
const series: ChartSeries[] = buildHistorySeries(historyResponse);

function renderChart(overrides: Partial<VPChartProps> = {}) {
  return render(
    <VPChart
      weeks={weeks}
      series={series}
      visibleTeamIds={series.map((entry) => entry.teamId)}
      selectedTeamId={null}
      onToggleTeam={() => {}}
      onIsolateTeam={() => {}}
      compact={false}
      {...overrides}
    />,
  );
}

describe("VPChart", () => {
  it("draws one labelled line per team with a summary for screen readers", () => {
    const { container } = renderChart();
    expect(
      screen.getByRole("img", { name: /cumulative victory points, weeks 1 to 4/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Alpha 10.83");
    const lines = container.querySelectorAll("polyline");
    expect(lines).toHaveLength(series.length);
    expect(container.querySelector('polyline[data-team-id="7"]')).toBeInTheDocument();
  });

  it("labels each line by name and final value in the full layout", () => {
    renderChart();
    expect(screen.getByText("Alpha 10.83")).toBeInTheDocument();
    expect(screen.getByText("Foxtrot -3.5")).toBeInTheDocument();
  });

  it("drops the end labels in the compact layout", () => {
    renderChart({ compact: true });
    expect(screen.queryByText("Alpha 10.83")).not.toBeInTheDocument();
  });

  it("highlights the selected team with a thicker line", () => {
    const { container } = renderChart({ selectedTeamId: 7 });
    expect(container.querySelector('polyline[data-team-id="7"]')).toHaveAttribute(
      "stroke-width",
      "3.2",
    );
    expect(container.querySelector('polyline[data-team-id="3"]')).toHaveAttribute(
      "stroke-width",
      "2.2",
    );
  });

  it("hides a series the legend toggles off", async () => {
    const onToggleTeam = vi.fn();
    const user = userEvent.setup();
    renderChart({ onToggleTeam });
    await user.click(screen.getByRole("button", { name: "Bravo 8.83" }));
    expect(onToggleTeam).toHaveBeenCalledWith(3);
  });

  it("isolates one team on a double-click while a single click still toggles", async () => {
    const onToggleTeam = vi.fn();
    const onIsolateTeam = vi.fn();
    const user = userEvent.setup();
    renderChart({ onToggleTeam, onIsolateTeam });

    const chip = screen.getByRole("button", { name: "Bravo 8.83" });
    expect(chip.getAttribute("title")).toContain("Double-click to show only Bravo");
    expect(screen.getByText(/Double-click a team to show only that team/)).toBeInTheDocument();

    await user.dblClick(chip);
    expect(onIsolateTeam).toHaveBeenCalledWith(3);
    expect(onToggleTeam).toHaveBeenCalledTimes(2);
  });

  it("marks hidden series with aria-pressed=false and a non-color cue", () => {
    const bareSeries = series.filter((entry) => entry.teamId !== 3);
    renderChart({ visibleTeamIds: bareSeries.map((entry) => entry.teamId) });
    const chip = screen.getByRole("button", { name: "Bravo 8.83" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(chip.className).toContain("line-through");
  });

  it("falls back to a data table for the chart values", () => {
    renderChart();
    expect(
      screen.getByRole("table", { name: /cumulative victory points per team, weeks 1 to 4/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("View chart data as a table")).toBeInTheDocument();
  });

  it("reports when there is no chart data", () => {
    renderChart({ weeks: [], series: [] });
    expect(screen.getByText("No chart data for this season yet.")).toBeInTheDocument();
  });
});
