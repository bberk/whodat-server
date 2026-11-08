import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TradeItem } from "../api/types";
import { TradeLogFeed } from "./TradeLogFeed";

const mockTrades: TradeItem[] = [
  {
    id: 1,
    external_trade_id: "trade-2027-1",
    trade_date: "2026-11-07T16:00:00Z",
    agreement_season: 2026,
    is_settled: false,
    discord_url: "https://discord.com/channels/1/2/3",
    summary: "Mahomes + 2027 1st for Justin Jefferson",
    conditions: [
      {
        id: "c1",
        description: "If Mahomes MVP, Bob pays $5 in 2027",
        draft_year: 2027,
        paying_team: "Team Bob",
        receiving_team: "Team Alice",
        amount: "5.00",
        status: "fulfilled",
      },
    ],
    parties: [
      {
        id: 1,
        owner_id: 1,
        franchise_key: null,
        team_name_raw: "Team Alice",
        players_sent: [{ name: "Patrick Mahomes", position: "QB" }],
        players_received: [{ name: "Justin Jefferson", position: "WR" }],
        draft_picks_sent: [{ draft_year: 2027, round: 1 }],
        draft_picks_received: [],
        auction_dollars: [
          { draft_year: 2027, amount: "-5.00" },
          { draft_year: 2028, amount: "-10.00" },
        ],
      },
      {
        id: 2,
        owner_id: 2,
        franchise_key: null,
        team_name_raw: "Team Bob",
        players_sent: [{ name: "Justin Jefferson", position: "WR" }],
        players_received: [{ name: "Patrick Mahomes", position: "QB" }],
        draft_picks_sent: [],
        draft_picks_received: [{ draft_year: 2027, round: 1 }],
        auction_dollars: [
          { draft_year: 2027, amount: "5.00" },
          { draft_year: 2028, amount: "10.00" },
        ],
      },
    ],
  },
  {
    id: 2,
    external_trade_id: "trade-2026-old",
    trade_date: "2026-09-01T12:00:00Z",
    agreement_season: 2026,
    is_settled: true,
    discord_url: null,
    summary: "Draft pick swap",
    conditions: [],
    parties: [
      {
        id: 3,
        owner_id: 3,
        franchise_key: null,
        team_name_raw: "Team Charlie",
        players_sent: [],
        players_received: [],
        draft_picks_sent: [{ draft_year: 2026, round: 2 }],
        draft_picks_received: [{ draft_year: 2026, round: 3 }],
        auction_dollars: [],
      },
      {
        id: 4,
        owner_id: 4,
        franchise_key: null,
        team_name_raw: "Team Dave",
        players_sent: [],
        players_received: [],
        draft_picks_sent: [{ draft_year: 2026, round: 3 }],
        draft_picks_received: [{ draft_year: 2026, round: 2 }],
        auction_dollars: [],
      },
    ],
  },
];

describe("TradeLogFeed", () => {
  it("renders list of trade cards with details and discord link", () => {
    render(
      <TradeLogFeed
        trades={mockTrades}
        allTeams={["Team Alice", "Team Bob", "Team Charlie", "Team Dave"]}
        allYears={[2026, 2027, 2028]}
      />,
    );

    expect(screen.getByText("#trade-2027-1")).toBeInTheDocument();
    expect(screen.getByText("#trade-2026-old")).toBeInTheDocument();
    expect(screen.getByText("Mahomes + 2027 1st for Justin Jefferson")).toBeInTheDocument();

    // Check Discord jump URL link
    const discordLink = screen.getByRole("link", { name: "View trade trade-2027-1 on Discord" });
    expect(discordLink).toHaveAttribute("href", "https://discord.com/channels/1/2/3");
    expect(discordLink).toHaveAttribute("target", "_blank");

    // Settled tag
    expect(screen.getByText("Settled / Drafted")).toBeInTheDocument();

    // Multi-draft pills
    expect(screen.getAllByText("2027 Draft").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("2028 Draft").length).toBeGreaterThanOrEqual(1);

    // Conditions block
    expect(screen.getByText("If Mahomes MVP, Bob pays $5 in 2027")).toBeInTheDocument();
    expect(screen.getByText("fulfilled")).toBeInTheDocument();
  });

  it("filters trades by team select", async () => {
    const user = userEvent.setup();
    render(
      <TradeLogFeed
        trades={mockTrades}
        allTeams={["Team Alice", "Team Bob", "Team Charlie", "Team Dave"]}
        allYears={[2026, 2027, 2028]}
      />,
    );

    const teamSelect = screen.getByLabelText("Team:");
    await user.selectOptions(teamSelect, "Team Charlie");

    expect(screen.queryByText("#trade-2027-1")).not.toBeInTheDocument();
    expect(screen.getByText("#trade-2026-old")).toBeInTheDocument();
    expect(screen.getByText("1 trade")).toBeInTheDocument();
  });

  it("filters trades by draft year select", async () => {
    const user = userEvent.setup();
    render(
      <TradeLogFeed
        trades={mockTrades}
        allTeams={["Team Alice", "Team Bob", "Team Charlie", "Team Dave"]}
        allYears={[2026, 2027, 2028]}
      />,
    );

    const yearSelect = screen.getByLabelText("Draft Year:");
    await user.selectOptions(yearSelect, "2027");

    expect(screen.getByText("#trade-2027-1")).toBeInTheDocument();
    expect(screen.queryByText("#trade-2026-old")).not.toBeInTheDocument();
  });

  it("filters trades by search text query", async () => {
    const user = userEvent.setup();
    render(
      <TradeLogFeed
        trades={mockTrades}
        allTeams={["Team Alice", "Team Bob", "Team Charlie", "Team Dave"]}
        allYears={[2026, 2027, 2028]}
      />,
    );

    const searchInput = screen.getByPlaceholderText("Player, team, or notes...");
    await user.type(searchInput, "Mahomes");

    expect(screen.getByText("#trade-2027-1")).toBeInTheDocument();
    expect(screen.queryByText("#trade-2026-old")).not.toBeInTheDocument();
  });

  it("shows empty state and allows resetting filters when no matches found", async () => {
    const user = userEvent.setup();
    render(
      <TradeLogFeed
        trades={mockTrades}
        allTeams={["Team Alice", "Team Bob", "Team Charlie", "Team Dave"]}
        allYears={[2026, 2027, 2028]}
      />,
    );

    const searchInput = screen.getByPlaceholderText("Player, team, or notes...");
    await user.type(searchInput, "NonexistentPlayerXYZ");

    expect(screen.getByText("No trades match your filters")).toBeInTheDocument();

    const clearButton = screen.getByRole("button", { name: "Clear filters" });
    await user.click(clearButton);

    expect(screen.getByText("#trade-2027-1")).toBeInTheDocument();
    expect(screen.getByText("#trade-2026-old")).toBeInTheDocument();
  });
});
