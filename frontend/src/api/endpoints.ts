/**
 * Typed calls to the Victory Points API (ARCHITECTURE.md section 8).
 *
 * The request and response types come from `schema.d.ts`, generated from `docs/openapi.json`.
 * Every function returns the parsed body or throws {@link ApiError}; callers decide how to show a
 * loading, empty, or error state.
 */

import { apiRequest } from "./client";
import type {
  AddLeagueRequest,
  AddLeagueResponse,
  AddSeasonRequest,
  AddSeasonResponse,
  CreateInviteRequest,
  CreateInviteResponse,
  CupWeekResponse,
  CupWeekUpdateRequest,
  EloConfigResponse,
  EloConfigUpdateRequest,
  EloHistoryResponse,
  LeagueMembersResponse,
  LeagueSummary,
  LoginRequest,
  LogoutResponse,
  MeResponse,
  OwnerUpdateRequest,
  OwnerUpdateResponse,
  OwnersResponse,
  PlayoffOddsResponse,
  PublicUser,
  RedeemInviteRequest,
  RedeemInviteResponse,
  RefreshResponse,
  SeasonRefreshResponse,
  SeasonSettingsResponse,
  SeasonsResponse,
  SignupRequest,
  SignupResponse,
  StandingsResponse,
  VpHistoryResponse,
  WapdateResponse,
} from "./types";

export const api = {
  me(signal?: AbortSignal): Promise<MeResponse> {
    return apiRequest<MeResponse>("/api/v1/me", { signal });
  },

  login(body: LoginRequest): Promise<PublicUser> {
    return apiRequest<PublicUser>("/api/v1/auth/login", { method: "POST", body });
  },

  signup(body: SignupRequest): Promise<SignupResponse> {
    return apiRequest<SignupResponse>("/api/v1/auth/signup", { method: "POST", body });
  },

  logout(): Promise<LogoutResponse> {
    return apiRequest<LogoutResponse>("/api/v1/auth/logout", { method: "POST" });
  },

  myLeagues(signal?: AbortSignal): Promise<LeagueSummary[]> {
    return apiRequest<LeagueSummary[]>("/api/v1/me/leagues", { signal });
  },

  redeemInvite(body: RedeemInviteRequest): Promise<RedeemInviteResponse> {
    return apiRequest<RedeemInviteResponse>("/api/v1/me/leagues/redeem-invite", {
      method: "POST",
      body,
    });
  },

  addLeague(body: AddLeagueRequest): Promise<AddLeagueResponse> {
    return apiRequest<AddLeagueResponse>("/api/v1/leagues", { method: "POST", body });
  },

  seasons(leagueId: number, signal?: AbortSignal): Promise<SeasonsResponse> {
    return apiRequest<SeasonsResponse>(`/api/v1/leagues/${leagueId}/seasons`, { signal });
  },

  addSeason(leagueId: number, body: AddSeasonRequest): Promise<AddSeasonResponse> {
    return apiRequest<AddSeasonResponse>(`/api/v1/leagues/${leagueId}/seasons`, {
      method: "POST",
      body,
    });
  },

  seasonSettings(leagueId: number, signal?: AbortSignal): Promise<SeasonSettingsResponse> {
    return apiRequest<SeasonSettingsResponse>(`/api/v1/leagues/${leagueId}/seasons/settings`, {
      signal,
    });
  },

  refreshSeason(leagueId: number, season: number): Promise<SeasonRefreshResponse> {
    return apiRequest<SeasonRefreshResponse>(
      `/api/v1/leagues/${leagueId}/seasons/${season}/refresh`,
      { method: "POST" },
    );
  },

  deleteSeason(leagueId: number, season: number): Promise<void> {
    return apiRequest<void>(`/api/v1/leagues/${leagueId}/seasons/${season}`, {
      method: "DELETE",
    });
  },

  owners(leagueId: number, signal?: AbortSignal): Promise<OwnersResponse> {
    return apiRequest<OwnersResponse>(`/api/v1/leagues/${leagueId}/owners`, { signal });
  },

  setOwner(leagueId: number, body: OwnerUpdateRequest): Promise<OwnerUpdateResponse> {
    return apiRequest<OwnerUpdateResponse>(`/api/v1/me/leagues/${leagueId}/owner`, {
      method: "PUT",
      body,
    });
  },

  refreshLeague(leagueId: number): Promise<RefreshResponse> {
    return apiRequest<RefreshResponse>(`/api/v1/leagues/${leagueId}/refresh`, {
      method: "POST",
    });
  },

  standings(leagueId: number, season: number, signal?: AbortSignal): Promise<StandingsResponse> {
    return apiRequest<StandingsResponse>(
      `/api/v1/leagues/${leagueId}/seasons/${season}/standings`,
      { signal },
    );
  },

  vpHistory(leagueId: number, season: number, signal?: AbortSignal): Promise<VpHistoryResponse> {
    return apiRequest<VpHistoryResponse>(
      `/api/v1/leagues/${leagueId}/seasons/${season}/vp-history`,
      { signal },
    );
  },

  wapdate(leagueId: number, season: number, signal?: AbortSignal): Promise<WapdateResponse> {
    return apiRequest<WapdateResponse>(`/api/v1/leagues/${leagueId}/seasons/${season}/wapdate`, {
      signal,
    });
  },

  playoffOdds(
    leagueId: number,
    season: number,
    options: {
      iterations?: number;
      seed?: number;
      strengthWeight?: string;
      signal?: AbortSignal;
    } = {},
  ): Promise<PlayoffOddsResponse> {
    const params = new URLSearchParams();
    if (options.iterations !== undefined) {
      params.set("iterations", String(options.iterations));
    }
    if (options.seed !== undefined) {
      params.set("seed", String(options.seed));
    }
    if (options.strengthWeight !== undefined) {
      params.set("strength_weight", options.strengthWeight);
    }
    const query = params.toString();
    return apiRequest<PlayoffOddsResponse>(
      `/api/v1/leagues/${leagueId}/seasons/${season}/playoff-odds${
        query === "" ? "" : `?${query}`
      }`,
      { signal: options.signal },
    );
  },

  eloHistory(
    leagueId: number,
    mode: "actual_schedule" | "round_robin",
    signal?: AbortSignal,
  ): Promise<EloHistoryResponse> {
    return apiRequest<EloHistoryResponse>(`/api/v1/leagues/${leagueId}/elo-history?mode=${mode}`, {
      signal,
    });
  },

  eloConfig(leagueId: number, signal?: AbortSignal): Promise<EloConfigResponse> {
    return apiRequest<EloConfigResponse>(`/api/v1/leagues/${leagueId}/elo-config`, { signal });
  },

  updateEloConfig(leagueId: number, body: EloConfigUpdateRequest): Promise<EloConfigResponse> {
    return apiRequest<EloConfigResponse>(`/api/v1/leagues/${leagueId}/elo-config`, {
      method: "PUT",
      body,
    });
  },

  cupWeek(leagueId: number, season: number, signal?: AbortSignal): Promise<CupWeekResponse> {
    return apiRequest<CupWeekResponse>(`/api/v1/leagues/${leagueId}/seasons/${season}/cup-week`, {
      signal,
    });
  },

  updateCupWeek(
    leagueId: number,
    season: number,
    body: CupWeekUpdateRequest,
  ): Promise<CupWeekResponse> {
    return apiRequest<CupWeekResponse>(`/api/v1/leagues/${leagueId}/seasons/${season}/cup-week`, {
      method: "PUT",
      body,
    });
  },

  members(leagueId: number, signal?: AbortSignal): Promise<LeagueMembersResponse> {
    return apiRequest<LeagueMembersResponse>(`/api/v1/leagues/${leagueId}/members`, { signal });
  },

  removeMember(leagueId: number, userId: number): Promise<void> {
    return apiRequest<void>(`/api/v1/leagues/${leagueId}/members/${userId}`, {
      method: "DELETE",
    });
  },

  createInvite(leagueId: number, body: CreateInviteRequest): Promise<CreateInviteResponse> {
    return apiRequest<CreateInviteResponse>(`/api/v1/leagues/${leagueId}/invites`, {
      method: "POST",
      body,
    });
  },

  deleteLeague(leagueId: number): Promise<void> {
    return apiRequest<void>(`/api/v1/leagues/${leagueId}`, { method: "DELETE" });
  },
};
