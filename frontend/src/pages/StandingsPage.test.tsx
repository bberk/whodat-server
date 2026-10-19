import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  createStandingsSource,
  mockStandingsBundle,
  type MockScenario,
  type StandingsSource,
} from "../mocks/standings";
import { StandingsPage } from "./StandingsPage";

function renderScenario(scenario: MockScenario) {
  return render(<StandingsPage source={createStandingsSource(scenario)} />);
}

describe("StandingsPage", () => {
  it("renders the overall table, one table per division, the chart, and the weekly breakdown", async () => {
    renderScenario("ready");
    const overall = await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(within(overall).getByRole("columnheader", { name: "W-L" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /east division standings/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /west division standings/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /cumulative victory points/i })).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: /week 4 victory point components/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 completed weeks/i)).toBeInTheDocument();
  });

  it("shows overall league ranks in the division tables", async () => {
    renderScenario("ready");
    const east = await screen.findByRole("table", { name: /east division standings/i });
    const west = screen.getByRole("table", { name: /west division standings/i });
    expect(
      within(east)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["1", "2", "3"]);
    expect(
      within(west)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["4", "5", "6"]);
  });

  it("highlights the selected team in both the table and the chart", async () => {
    const user = userEvent.setup();
    const { container } = renderScenario("ready");
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    const alpha = screen.getAllByRole("button", { name: "Alpha" })[0];
    await user.click(alpha);
    expect(alpha).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('polyline[data-team-id="7"]')).toHaveAttribute(
      "stroke-width",
      "3.2",
    );
  });

  it("toggles a chart series off from the legend", async () => {
    const user = userEvent.setup();
    const { container } = renderScenario("ready");
    await screen.findByRole("img", { name: /cumulative victory points/i });
    const chip = screen.getByRole("button", { name: "Bravo 8.83" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(container.querySelector('polyline[data-team-id="3"]')).not.toBeInTheDocument();
    expect(screen.getByRole("img").getAttribute("aria-label")).not.toContain("Bravo");
  });

  it("re-shows a hidden team when it is selected from the table", async () => {
    const user = userEvent.setup();
    const { container } = renderScenario("ready");
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    await user.click(screen.getByRole("button", { name: "Bravo 8.83" }));
    expect(container.querySelector('polyline[data-team-id="3"]')).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Bravo" })[0]);
    expect(container.querySelector('polyline[data-team-id="3"]')).toBeInTheDocument();
  });

  it("switches the weekly breakdown to the selected week", async () => {
    const user = userEvent.setup();
    renderScenario("ready");
    await screen.findByRole("table", { name: /week 4 victory point components/i });
    await user.click(screen.getByRole("button", { name: "W1" }));
    expect(
      await screen.findByRole("table", { name: /week 1 victory point components/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/week 1 mirrors ACCEPTANCE.md example A/i)).toBeInTheDocument();
  });

  it("keeps the season picker controlled", async () => {
    renderScenario("ready");
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    const select = screen.getByLabelText("Season");
    fireEvent.change(select, { target: { value: "2026" } });
    expect(select).toHaveValue("2026");
  });

  it("offers the VP rules summary accessibly", async () => {
    renderScenario("ready");
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(screen.getByRole("tooltip")).toHaveTextContent(/head-to-head win/i);
  });

  it("labels the data as illustrative and explains the mock source", async () => {
    renderScenario("ready");
    await screen.findByRole("table", { name: /overall 2026 standings/i });
    expect(screen.getByRole("note")).toHaveTextContent(/illustrative data/i);
    expect(screen.getByText(/mock data provenance/i)).toBeInTheDocument();
  });

  it("shows a loading state for every data view", () => {
    renderScenario("loading");
    expect(screen.getAllByRole("status")).toHaveLength(4);
    expect(screen.getByRole("status", { name: "Loading standings…" })).toBeInTheDocument();
  });

  it("shows an empty state for every data view", async () => {
    renderScenario("empty");
    await screen.findByText("No chart yet");
    expect(screen.getAllByText("No completed weeks yet")).toHaveLength(2);
    expect(screen.getByText("No weekly VP yet")).toBeInTheDocument();
  });

  it("shows an error state with a retry that reloads the data", async () => {
    let calls = 0;
    const source: StandingsSource = {
      load: () => {
        calls += 1;
        return calls === 1
          ? Promise.reject(new Error("boom"))
          : Promise.resolve(mockStandingsBundle);
      },
    };
    const user = userEvent.setup();
    render(<StandingsPage source={source} />);
    expect(await screen.findAllByRole("alert")).toHaveLength(4);
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    expect(
      await screen.findByRole("table", { name: /overall 2026 standings/i }),
    ).toBeInTheDocument();
  });

  it("defaults to the bundled mock source when none is injected", async () => {
    render(<StandingsPage />);
    expect(
      await screen.findByRole("table", { name: /overall 2026 standings/i }),
    ).toBeInTheDocument();
  });
});
