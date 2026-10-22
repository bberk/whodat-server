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
  LeagueSummary,
  LoginRequest,
  LogoutResponse,
  MeResponse,
  OwnerUpdateRequest,
  OwnerUpdateResponse,
  OwnersResponse,
  PublicUser,
  RedeemInviteRequest,
  RedeemInviteResponse,
  RefreshResponse,
  SeasonsResponse,
  SignupRequest,
  SignupResponse,
  StandingsResponse,
  VpHistoryResponse,
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
};
