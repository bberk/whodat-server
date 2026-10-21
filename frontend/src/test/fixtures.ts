/**
 * Deterministic API payloads for Vitest. Tests mock `fetch`; these fixtures never touch a network
 * and are not shipped in the app bundle.
 */

import { vi } from "vitest";

import type {
  LeagueSummary,
  MeResponse,
  OwnerSummary,
  SignupLeague,
  StandingsResponse,
  VpHistoryResponse,
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
