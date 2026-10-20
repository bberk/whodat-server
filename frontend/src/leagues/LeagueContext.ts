import { createContext, useContext } from "react";

import type { LeagueSummary } from "../api/types";

export type LoadStatus = "loading" | "ready" | "error";

export interface LeagueContextValue {
  leagues: LeagueSummary[];
  leaguesStatus: LoadStatus;
  leaguesError: string | null;
  selectedLeague: LeagueSummary | null;
  selectLeague: (leagueId: number) => void;

  seasons: number[];
  seasonsStatus: LoadStatus;
  seasonsError: string | null;
  season: number | null;
  selectSeason: (season: number) => void;

  /** Insert or replace one membership after adding a league or changing its owner. */
  upsertLeague: (league: LeagueSummary) => void;
  reloadLeagues: () => void;
  /** Increment after a successful refresh so data views re-fetch. */
  dataVersion: number;
  notifyDataChanged: () => void;
}

export const LeagueContext = createContext<LeagueContextValue | null>(null);

/** Read the selected league and season. Throws when called outside {@link LeagueProvider}. */
export function useLeague(): LeagueContextValue {
  const value = useContext(LeagueContext);
  if (value === null) {
    throw new Error("useLeague must be used inside LeagueProvider");
  }
  return value;
}
