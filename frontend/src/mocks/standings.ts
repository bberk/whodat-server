/**
 * Isolated mock data source and view-model for the standings UI.
 *
 * The standings API and its exported OpenAPI document do not exist yet (SPEC.md M4), so this
 * module is the only place the standings UI reads data from. The response shapes mirror
 * ARCHITECTURE.md §8 (`GET .../standings` and `GET .../vp-history`); the weekly VP component
 * breakdown mirrors the `score` row's component columns, which §8 does not expose yet.
 *
 * Every number is illustrative fixture data derived from the ACCEPTANCE.md §1.1 worked examples,
 * and the UI labels it as such. Nothing here calls ESPN, the network, or any backend.
 */

export interface StandingsRow {
  rank: number;
  team_id: number;
  team_name: string;
  owner_name: string;
  division: string;
  victory_points: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: string;
  weekly_vp: string[];
}

export interface DivisionStandings {
  name: string;
  standings: StandingsRow[];
}

export interface StandingsResponse {
  league_id: number;
  season: number;
  completed_weeks: number;
  overall: StandingsRow[];
  divisions: DivisionStandings[];
}

export interface VPHistoryTeam {
  team_id: number;
  team_name: string;
  weekly: string[];
  cumulative: string[];
}

export interface VPHistoryResponse {
  weeks: number[];
  teams: VPHistoryTeam[];
}

/**
 * Weekly VP components for one week. Not part of the §8 contract yet; the real endpoint would
 * expose the `score` components (h2h, top_half, high, low) so the UI can explain a team's week.
 */
export interface WeeklyVPComponentRow {
  team_id: number;
  h2h: string;
  top_half: string;
  high: string;
  low: string;
  total: string;
}

export interface WeeklyVPComponents {
  week: number;
  note: string | null;
  rows: WeeklyVPComponentRow[];
}

export interface StandingsBundle {
  standings: StandingsResponse;
  history: VPHistoryResponse;
  weekly: WeeklyVPComponents[];
}

/**
 * Season 2026: 6 teams, 2 divisions, 4 completed weeks. Week 1 = ACCEPTANCE example A, week 2 =
 * example B with the head-to-head tie removed, week 3 = example C, week 4 = example D. Because no
 * matchup was tied, every row's `ties` is 0 and the tables show W-L rather than W-L-T.
 */
export const mockStandingsBundle: StandingsBundle = {
  standings: {
    league_id: 1,
    season: 2026,
    completed_weeks: 4,
    overall: [
      {
        rank: 1,
        team_id: 7,
        team_name: "Alpha",
        owner_name: "Alex",
        division: "East",
        victory_points: "10.83",
        wins: 4,
        losses: 0,
        ties: 0,
        points_for: "495.00",
        weekly_vp: ["2.5", "3", "3", "2.33"],
      },
      {
        rank: 2,
        team_id: 3,
        team_name: "Bravo",
        owner_name: "Blair",
        division: "East",
        victory_points: "8.83",
        wins: 4,
        losses: 0,
        ties: 0,
        points_for: "475.00",
        weekly_vp: ["2.5", "2", "2", "2.33"],
      },
      {
        rank: 3,
        team_id: 9,
        team_name: "Charlie",
        owner_name: "Casey",
        division: "East",
        victory_points: "5.5",
        wins: 3,
        losses: 1,
        ties: 0,
        points_for: "405.00",
        weekly_vp: ["2", "1.5", "2", "0"],
      },
      {
        rank: 4,
        team_id: 5,
        team_name: "Echo",
        owner_name: "Emery",
        division: "West",
        victory_points: "1.83",
        wins: 1,
        losses: 3,
        ties: 0,
        points_for: "355.00",
        weekly_vp: ["0", "0", "-0.5", "2.33"],
      },
      {
        rank: 5,
        team_id: 2,
        team_name: "Delta",
        owner_name: "Devon",
        division: "West",
        victory_points: "0.5",
        wins: 0,
        losses: 4,
        ties: 0,
        points_for: "370.00",
        weekly_vp: ["0", "0.5", "0", "0"],
      },
      {
        rank: 6,
        team_id: 4,
        team_name: "Foxtrot",
        owner_name: "Frankie",
        division: "West",
        victory_points: "-3.5",
        wins: 0,
        losses: 4,
        ties: 0,
        points_for: "300.00",
        weekly_vp: ["-1", "-1", "-0.5", "-1"],
      },
    ],
    divisions: [
      {
        name: "East",
        standings: [
          {
            rank: 1,
            team_id: 7,
            team_name: "Alpha",
            owner_name: "Alex",
            division: "East",
            victory_points: "10.83",
            wins: 4,
            losses: 0,
            ties: 0,
            points_for: "495.00",
            weekly_vp: ["2.5", "3", "3", "2.33"],
          },
          {
            rank: 2,
            team_id: 3,
            team_name: "Bravo",
            owner_name: "Blair",
            division: "East",
            victory_points: "8.83",
            wins: 4,
            losses: 0,
            ties: 0,
            points_for: "475.00",
            weekly_vp: ["2.5", "2", "2", "2.33"],
          },
          {
            rank: 3,
            team_id: 9,
            team_name: "Charlie",
            owner_name: "Casey",
            division: "East",
            victory_points: "5.5",
            wins: 3,
            losses: 1,
            ties: 0,
            points_for: "405.00",
            weekly_vp: ["2", "1.5", "2", "0"],
          },
        ],
      },
      {
        name: "West",
        standings: [
          {
            rank: 1,
            team_id: 5,
            team_name: "Echo",
            owner_name: "Emery",
            division: "West",
            victory_points: "1.83",
            wins: 1,
            losses: 3,
            ties: 0,
            points_for: "355.00",
            weekly_vp: ["0", "0", "-0.5", "2.33"],
          },
          {
            rank: 2,
            team_id: 2,
            team_name: "Delta",
            owner_name: "Devon",
            division: "West",
            victory_points: "0.5",
            wins: 0,
            losses: 4,
            ties: 0,
            points_for: "370.00",
            weekly_vp: ["0", "0.5", "0", "0"],
          },
          {
            rank: 3,
            team_id: 4,
            team_name: "Foxtrot",
            owner_name: "Frankie",
            division: "West",
            victory_points: "-3.5",
            wins: 0,
            losses: 4,
            ties: 0,
            points_for: "300.00",
            weekly_vp: ["-1", "-1", "-0.5", "-1"],
          },
        ],
      },
    ],
  },
  history: {
    weeks: [1, 2, 3, 4],
    teams: [
      {
        team_id: 7,
        team_name: "Alpha",
        weekly: ["2.5", "3", "3", "2.33"],
        cumulative: ["2.5", "5.5", "8.5", "10.83"],
      },
      {
        team_id: 3,
        team_name: "Bravo",
        weekly: ["2.5", "2", "2", "2.33"],
        cumulative: ["2.5", "4.5", "6.5", "8.83"],
      },
      {
        team_id: 9,
        team_name: "Charlie",
        weekly: ["2", "1.5", "2", "0"],
        cumulative: ["2", "3.5", "5.5", "5.5"],
      },
      {
        team_id: 2,
        team_name: "Delta",
        weekly: ["0", "0.5", "0", "0"],
        cumulative: ["0", "0.5", "0.5", "0.5"],
      },
      {
        team_id: 5,
        team_name: "Echo",
        weekly: ["0", "0", "-0.5", "2.33"],
        cumulative: ["0", "0", "-0.5", "1.83"],
      },
      {
        team_id: 4,
        team_name: "Foxtrot",
        weekly: ["-1", "-1", "-0.5", "-1"],
        cumulative: ["-1", "-2", "-2.5", "-3.5"],
      },
    ],
  },
  weekly: [
    {
      week: 1,
      note:
        "Week 1 mirrors ACCEPTANCE.md example A: Alpha and Bravo tie for the highest score and " +
        "split the high-score point 0.5 each; Foxtrot takes the -1 for the lowest score.",
      rows: [
        { team_id: 7, h2h: "1", top_half: "1", high: "0.5", low: "0", total: "2.5" },
        { team_id: 3, h2h: "1", top_half: "1", high: "0.5", low: "0", total: "2.5" },
        { team_id: 9, h2h: "1", top_half: "1", high: "0", low: "0", total: "2" },
        { team_id: 2, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 5, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 4, h2h: "0", top_half: "0", high: "0", low: "-1", total: "-1" },
      ],
    },
    {
      week: 2,
      note:
        "Week 2 mirrors ACCEPTANCE.md example B with the head-to-head tie removed: Charlie and " +
        "Delta still tie across the top-half cutoff and share 0.5 top-half VP each.",
      rows: [
        { team_id: 7, h2h: "1", top_half: "1", high: "1", low: "0", total: "3" },
        { team_id: 3, h2h: "1", top_half: "1", high: "0", low: "0", total: "2" },
        { team_id: 9, h2h: "1", top_half: "0.5", high: "0", low: "0", total: "1.5" },
        { team_id: 2, h2h: "0", top_half: "0.5", high: "0", low: "0", total: "0.5" },
        { team_id: 5, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 4, h2h: "0", top_half: "0", high: "0", low: "-1", total: "-1" },
      ],
    },
    {
      week: 3,
      note:
        "Week 3 mirrors ACCEPTANCE.md example C: Echo and Foxtrot tie for the lowest score and " +
        "each take -0.5.",
      rows: [
        { team_id: 7, h2h: "1", top_half: "1", high: "1", low: "0", total: "3" },
        { team_id: 3, h2h: "1", top_half: "1", high: "0", low: "0", total: "2" },
        { team_id: 9, h2h: "1", top_half: "1", high: "0", low: "0", total: "2" },
        { team_id: 2, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 5, h2h: "0", top_half: "0", high: "0", low: "-0.5", total: "-0.5" },
        { team_id: 4, h2h: "0", top_half: "0", high: "0", low: "-0.5", total: "-0.5" },
      ],
    },
    {
      week: 4,
      note:
        "Week 4 mirrors ACCEPTANCE.md example D: Alpha, Bravo, and Echo tie for the highest " +
        "score and split the high-score point exactly 1/3 each, displayed as 0.33.",
      rows: [
        { team_id: 7, h2h: "1", top_half: "1", high: "0.33", low: "0", total: "2.33" },
        { team_id: 3, h2h: "1", top_half: "1", high: "0.33", low: "0", total: "2.33" },
        { team_id: 9, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 2, h2h: "0", top_half: "0", high: "0", low: "0", total: "0" },
        { team_id: 5, h2h: "1", top_half: "1", high: "0.33", low: "0", total: "2.33" },
        { team_id: 4, h2h: "0", top_half: "0", high: "0", low: "-1", total: "-1" },
      ],
    },
  ],
};

/** A season with no completed weeks: every data view falls back to its empty state. */
export const emptyStandingsBundle: StandingsBundle = {
  standings: { league_id: 1, season: 2026, completed_weeks: 0, overall: [], divisions: [] },
  history: { weeks: [], teams: [] },
  weekly: [],
};

export type MockScenario = "ready" | "empty" | "error" | "loading";

export interface StandingsSource {
  load: () => Promise<StandingsBundle>;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/** Build a stand-in for the future standings client, one per UI state a data view must handle. */
export function createStandingsSource(
  scenario: MockScenario = "ready",
  delayMs = 0,
): StandingsSource {
  return {
    load: () => {
      if (scenario === "loading") {
        return new Promise<StandingsBundle>(() => {});
      }
      if (scenario === "error") {
        return Promise.reject(new Error("The standings request failed"));
      }
      const bundle = scenario === "empty" ? emptyStandingsBundle : mockStandingsBundle;
      return delay(delayMs).then(() => bundle);
    },
  };
}

export const defaultStandingsSource: StandingsSource = createStandingsSource();

/** True when any team recorded an H2H tie, which switches the record column to W-L-T. */
export function seasonHasHeadToHeadTies(rows: StandingsRow[]): boolean {
  return rows.some((row) => row.ties > 0);
}

/**
 * The chart series, in history order. `styleIndex` drives the color/dash/marker pairing so a team
 * keeps the same visual identity in the table tag, the legend, and the chart.
 */
export interface HistorySeries {
  teamId: number;
  teamName: string;
  styleIndex: number;
  weekly: string[];
  cumulative: string[];
}

export function buildHistorySeries(bundle: StandingsBundle): HistorySeries[] {
  return bundle.history.teams.map((team, index) => ({
    teamId: team.team_id,
    teamName: team.team_name,
    styleIndex: index,
    weekly: team.weekly,
    cumulative: team.cumulative,
  }));
}

export function seriesIndexByTeamId(bundle: StandingsBundle): Map<number, number> {
  return new Map(bundle.history.teams.map((team, index) => [team.team_id, index]));
}

/** Weekly VP components for one week, ordered by that week's total VP then overall rank. */
export interface WeeklyBreakdownRow {
  teamId: number;
  teamName: string;
  styleIndex: number;
  h2h: string;
  topHalf: string;
  high: string;
  low: string;
  total: string;
  overallRank: number;
}

export interface WeeklyBreakdown {
  rows: WeeklyBreakdownRow[];
  note: string | null;
}

export function weeklyBreakdownFor(bundle: StandingsBundle, week: number): WeeklyBreakdown {
  const entry = bundle.weekly.find((candidate) => candidate.week === week);
  if (entry === undefined) {
    return { rows: [], note: null };
  }
  const rankByTeam = new Map(bundle.standings.overall.map((row) => [row.team_id, row.rank]));
  const nameByTeam = new Map(bundle.history.teams.map((team) => [team.team_id, team.team_name]));
  const styleByTeam = seriesIndexByTeamId(bundle);
  const rows = entry.rows.map((row) => ({
    teamId: row.team_id,
    teamName: nameByTeam.get(row.team_id) ?? "",
    styleIndex: styleByTeam.get(row.team_id) ?? 0,
    h2h: row.h2h,
    topHalf: row.top_half,
    high: row.high,
    low: row.low,
    total: row.total,
    overallRank: rankByTeam.get(row.team_id) ?? 0,
  }));
  rows.sort((a, b) => Number(b.total) - Number(a.total) || a.overallRank - b.overallRank);
  return { rows, note: entry.note };
}
