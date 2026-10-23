/**
 * Deterministic API payloads for Vitest. Tests mock `fetch`; these fixtures never touch a network
 * and are not shipped in the app bundle.
 */

import { vi } from "vitest";

import type {
  EloConfigResponse,
  EloHistoryResponse,
  LeagueMemberSummary,
  LeagueSummary,
  MeResponse,
  OwnerSummary,
  SeasonSettingsResponse,
  SignupLeague,
  StandingsResponse,
  VpHistoryResponse,
  WapdateResponse,
} from "../api/types";

export const adminUser: MeResponse = {
  id: 1,
  email: "admin@example.com",
  role: "admin",
  has_league: true,
};
export const memberUser: MeResponse = {
  id: 2,
  email: "member@example.com",
  role: "member",
  has_league: true,
};
/** An admin who signed up with an admin invite and still owes the onboarding step. */
export const adminWithoutLeague: MeResponse = {
  id: 3,
  email: "new-admin@example.com",
  role: "admin",
  has_league: false,
};

export const signupLeague: SignupLeague = {
  league_id: 1,
  provider: "espn",
  external_id: "111111",
  name: "Alpha League",
};

export const leagueAlpha: LeagueSummary = {
  league_id: 1,
  provider: "espn",
  external_id: "111111",
  name: "Alpha League",
  owner_id: 7,
  has_credentials: true,
};

export const leagueBeta: LeagueSummary = {
  league_id: 2,
  provider: "espn",
  external_id: "222222",
  name: "Beta League",
  owner_id: null,
  has_credentials: false,
};

export const owners: OwnerSummary[] = [
  { id: 7, external_id: "{7}", display_name: "Alex" },
  { id: 3, external_id: "{3}", display_name: "Blair" },
  { id: 9, external_id: "{9}", display_name: "Casey" },
];

export const leagueMembers: LeagueMemberSummary[] = [
  {
    user_id: 1,
    email: "admin@example.com",
    role: "admin",
    owner_id: 7,
    owner_name: "Alex",
    has_credentials: true,
  },
  {
    user_id: 2,
    email: "member@example.com",
    role: "member",
    owner_id: null,
    owner_name: null,
    has_credentials: false,
  },
];

export const seasonSettingsResponse: SeasonSettingsResponse = {
  seasons: [
    {
      season: 2025,
      cup_week: null,
      regular_season_length: 14,
      last_refreshed_at: "2026-10-20T15:30:00+00:00",
    },
    {
      season: 2026,
      cup_week: 1,
      regular_season_length: 2,
      last_refreshed_at: null,
    },
  ],
};

export const standingsResponse: StandingsResponse = {
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
      points_for: "495",
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
      points_for: "475",
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
      points_for: "405",
      weekly_vp: ["2", "1.5", "2", "0"],
    },
    {
      rank: 4,
      team_id: 5,
      team_name: "Echo",
      owner_name: null,
      division: "West",
      victory_points: "1.83",
      wins: 1,
      losses: 3,
      ties: 0,
      points_for: "355",
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
      points_for: "370",
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
      points_for: "300",
      weekly_vp: ["-1", "-1", "-0.5", "-1"],
    },
  ],
  divisions: [
    {
      name: "East",
      standings: [],
    },
    {
      name: "West",
      standings: [],
    },
  ],
};

// Division rows keep their overall league rank; build them from the overall rows.
standingsResponse.divisions = standingsResponse.divisions.map((division) => ({
  ...division,
  standings: standingsResponse.overall.filter((row) => row.division === division.name),
}));

export const historyResponse: VpHistoryResponse = {
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
};

export const emptyStandingsResponse: StandingsResponse = {
  league_id: 1,
  season: 2026,
  completed_weeks: 0,
  overall: [],
  divisions: [],
};

export const emptyHistoryResponse: VpHistoryResponse = { weeks: [], teams: [] };

export const wapdateResponse: WapdateResponse = {
  league_id: 1,
  season: 2026,
  highest_completed_week: 6,
  periods: [
    {
      period: 1,
      start_week: 1,
      end_week: 4,
      status: "complete",
      weeks: [1, 2, 3, 4],
      rows: [
        {
          team_id: 9,
          team_name: "Charlie",
          victory_points: "-2",
          wins: 0,
          points_for: "180",
          eliminated: false,
        },
        {
          team_id: 2,
          team_name: "Delta",
          victory_points: "1",
          wins: 1,
          points_for: "205",
          eliminated: false,
        },
        {
          team_id: 3,
          team_name: "Bravo",
          victory_points: "3",
          wins: 1,
          points_for: "215",
          eliminated: false,
        },
        {
          team_id: 7,
          team_name: "Alpha",
          victory_points: "7",
          wins: 2,
          points_for: "250",
          eliminated: false,
        },
      ],
    },
    {
      period: 2,
      start_week: 5,
      end_week: 8,
      status: "current",
      weeks: [5, 6],
      rows: [
        {
          team_id: 4,
          team_name: "Foxtrot",
          victory_points: "0",
          wins: 0,
          points_for: "150",
          eliminated: false,
        },
        {
          team_id: 2,
          team_name: "Delta",
          victory_points: "2",
          wins: 1,
          points_for: "205",
          eliminated: false,
        },
        {
          team_id: 3,
          team_name: "Bravo",
          victory_points: "5",
          wins: 1,
          points_for: "220",
          eliminated: false,
        },
        {
          team_id: 7,
          team_name: "Alpha",
          victory_points: "10",
          wins: 2,
          points_for: "260",
          eliminated: true,
        },
      ],
    },
  ],
};

export const emptyWapdateResponse: WapdateResponse = {
  league_id: 1,
  season: 2026,
  highest_completed_week: null,
  periods: [],
};

export interface JsonResponseInit {
  status?: number;
  headers?: Record<string, string>;
}

/** Build a JSON `Response` with the headers the client expects. */
export function jsonResponse(body: unknown, init: JsonResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(body), { status: init.status ?? 200, headers });
}

/** Build a structured API error body, optionally with a 429 `Retry-After` header. */
export function errorResponse(
  status: number,
  detail: { code: string; message: string } | unknown[] | string,
  retryAfter?: number,
): Response {
  const headers: Record<string, string> = {};
  if (retryAfter !== undefined) {
    headers["Retry-After"] = String(retryAfter);
  }
  return jsonResponse({ detail }, { status, headers });
}

export type FetchHandler = (url: string, init: RequestInit) => Response | Promise<Response>;

/** Replace the global fetch with a handler and return the mock for assertions. */
export function mockFetch(handler: FetchHandler) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    return handler(String(input), init ?? {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The pathname of a request URL, for routing a fetch mock. */
export function requestPath(url: string): string {
  return new URL(url).pathname;
}

/** Parse a JSON request body from a fetch mock call. */
export function requestBody(init: RequestInit): Record<string, unknown> {
  if (typeof init.body !== "string") {
    return {};
  }
  return JSON.parse(init.body) as Record<string, unknown>;
}

export const eloConfigResponse: EloConfigResponse = {
  league_id: 1,
  starting_rating: "1500",
  k_factor: "24",
  margin_weight: "0.25",
  margin_cap: "50",
  season_regression: "0.333333",
};

/** Two seasons, one cup week, a new 2026 franchise, and a renamed team. */
export const eloHistoryResponse: EloHistoryResponse = {
  league_id: 1,
  mode: "round_robin",
  seasons: [2025, 2026],
  config: {
    starting_rating: "1500",
    k_factor: "24",
    margin_weight: "0.25",
    margin_cap: "50",
    season_regression: "0.333333",
  },
  weeks: [
    { index: 0, season: 2025, week: 1, is_cup_week: false, is_season_start: true, rated: true },
    { index: 1, season: 2025, week: 2, is_cup_week: true, is_season_start: false, rated: false },
    { index: 2, season: 2026, week: 1, is_cup_week: false, is_season_start: true, rated: true },
  ],
  season_boundaries: [{ season: 2026, week_index: 2 }],
  teams: [
    {
      team_key: "espn:1",
      team_id: 7,
      name: "Alpha",
      owner_name: "Alex",
      aliases: ["Alpha Old"],
      first_season: 2025,
      last_season: 2026,
      series: ["1512.6", "1512.6", "1525.2"],
      seasons: [
        {
          season: 2025,
          start_rating: "1500",
          end_rating: "1512.6",
          change: "12.6",
          rated_weeks: 1,
        },
        {
          season: 2026,
          start_rating: "1508.4",
          end_rating: "1525.2",
          change: "16.8",
          rated_weeks: 1,
        },
      ],
      current: "1525.2",
      last_change: "12.6",
      season_change: "16.8",
      peak: "1525.2",
      peak_at: { season: 2026, week: 1 },
      low: "1500",
      low_at: null,
      rated_weeks: 2,
    },
    {
      team_key: "espn:2",
      team_id: 3,
      name: "Bravo",
      owner_name: "Blair",
      aliases: [],
      first_season: 2025,
      last_season: 2026,
      series: ["1487.4", "1487.4", "1474.8"],
      seasons: [
        {
          season: 2025,
          start_rating: "1500",
          end_rating: "1487.4",
          change: "-12.6",
          rated_weeks: 1,
        },
        {
          season: 2026,
          start_rating: "1491.6",
          end_rating: "1474.8",
          change: "-16.8",
          rated_weeks: 1,
        },
      ],
      current: "1474.8",
      last_change: "-12.6",
      season_change: "-16.8",
      peak: "1500",
      peak_at: null,
      low: "1474.8",
      low_at: { season: 2026, week: 1 },
      rated_weeks: 2,
    },
    {
      team_key: "espn:3",
      team_id: 9,
      name: "Charlie",
      owner_name: null,
      aliases: [],
      first_season: 2026,
      last_season: 2026,
      series: [null, null, "1512.6"],
      seasons: [
        {
          season: 2026,
          start_rating: "1500",
          end_rating: "1512.6",
          change: "12.6",
          rated_weeks: 1,
        },
      ],
      current: "1512.6",
      last_change: "12.6",
      season_change: "12.6",
      peak: "1512.6",
      peak_at: { season: 2026, week: 1 },
      low: "1500",
      low_at: null,
      rated_weeks: 1,
    },
  ],
  unrated_teams: [{ team_key: "espn:4", name: "Delta", reason: "No rated matchups yet" }],
  warnings: [],
};

export const emptyEloHistoryResponse: EloHistoryResponse = {
  ...eloHistoryResponse,
  weeks: [],
  season_boundaries: [],
  teams: [],
};
