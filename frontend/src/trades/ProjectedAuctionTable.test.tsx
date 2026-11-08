import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TeamBudgetProjectionItem } from "../api/types";
import { ProjectedAuctionTable } from "./ProjectedAuctionTable";

const mockProjections: TeamBudgetProjectionItem[] = [
  {
    team_id: "Team Alice",
    starting_budget: "200.00",
    base_trade_delta: "-5.00",
    fulfilled_conditional_delta: "5.00",
    net_delta: "0.00",
    projected_budget: "200.00",
    pending_conditional_delta: "0.00",
    is_negative_budget: false,
  },
  {
    team_id: "Team Bob",
    starting_budget: "200.00",
    base_trade_delta: "15.00",
    fulfilled_conditional_delta: "-5.00",
    net_delta: "10.00",
    projected_budget: "210.00",
    pending_conditional_delta: "5.00",
    is_negative_budget: false,
  },
  {
    team_id: "Team Charlie",
    starting_budget: "200.00",
    base_trade_delta: "-250.00",
    fulfilled_conditional_delta: "0.00",
    net_delta: "-250.00",
    projected_budget: "-50.00",
    pending_conditional_delta: "0.00",
    is_negative_budget: true,
  },
];

describe("ProjectedAuctionTable", () => {
  it("renders draft year title, base budget, and team projection rows", () => {
    render(
      <ProjectedAuctionTable draftYear={2027} baseBudget="200.00" projections={mockProjections} />,
    );

    expect(
      screen.getByRole("heading", { name: "Projected Auction Dollars — 2027 Draft" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Base league budget:/)).toBeInTheDocument();

    expect(screen.getByText("Team Alice")).toBeInTheDocument();
    expect(screen.getByText("Team Bob")).toBeInTheDocument();
    expect(screen.getByText("Team Charlie")).toBeInTheDocument();

    // Positive and negative deltas
    expect(screen.getAllByText("-$5.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("+$15.00")).toBeInTheDocument();
    expect(screen.getByText("+$10.00")).toBeInTheDocument();
    expect(screen.getAllByText("-$250.00").length).toBeGreaterThanOrEqual(1);
  });

  it("renders Deficit badge on negative budget teams", () => {
    render(
      <ProjectedAuctionTable draftYear={2027} baseBudget="200.00" projections={mockProjections} />,
    );

    const deficitBadges = screen.getAllByText("Deficit");
    expect(deficitBadges).toHaveLength(1);
    expect(deficitBadges[0]).toHaveAttribute("title", "Projected budget is negative");
  });

  it("renders fulfilled and pending conditions badges and tooltips", () => {
    render(
      <ProjectedAuctionTable draftYear={2027} baseBudget="200.00" projections={mockProjections} />,
    );

    // Team Bob has pending condition 5.00 (P)
    expect(screen.getByText("+$5.00 (P)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Conditions for Team Bob" })).toBeInTheDocument();
  });

  it("sorts rows when clicking sortable column headers", async () => {
    const user = userEvent.setup();
    render(
      <ProjectedAuctionTable draftYear={2027} baseBudget="200.00" projections={mockProjections} />,
    );

    // Default sort is projected desc: Bob ($210), Alice ($200), Charlie (-$50)
    let rows = screen.getAllByRole("row");
    // Row 0 is header, Row 1 is first team
    expect(rows[1]).toHaveTextContent("Team Bob");
    expect(rows[2]).toHaveTextContent("Team Alice");
    expect(rows[3]).toHaveTextContent("Team Charlie");

    // Click "Team" header to sort by Team Name ascending
    const teamHeader = screen.getByRole("button", { name: "Sort by Team" });
    await user.click(teamHeader);

    rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Team Alice");
    expect(rows[2]).toHaveTextContent("Team Bob");
    expect(rows[3]).toHaveTextContent("Team Charlie");

    // Click "Team" again for descending
    await user.click(teamHeader);
    rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Team Charlie");
    expect(rows[2]).toHaveTextContent("Team Bob");
    expect(rows[3]).toHaveTextContent("Team Alice");
  });

  it("renders empty state message when projections array is empty", () => {
    render(<ProjectedAuctionTable draftYear={2027} baseBudget="200.00" projections={[]} />);

    expect(screen.getByText("No teams found for auction budget projection.")).toBeInTheDocument();
  });
});
