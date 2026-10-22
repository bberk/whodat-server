import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/endpoints";
import type { LeagueSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LeagueContext, type LoadStatus } from "./LeagueContext";

function latestSeason(seasons: readonly number[]): number | null {
  return seasons.length === 0 ? null : Math.max(...seasons);
}

/**
 * Load the caller's memberships on sign-in, default to the first league and its latest season, and
 * keep the selected season in sync when the league changes. Adding a league or setting an owner
 * updates this list in place; a successful refresh bumps `dataVersion` so data views re-fetch.
 */
export function LeagueProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [leaguesStatus, setLeaguesStatus] = useState<LoadStatus>("loading");
  const [leaguesError, setLeaguesError] = useState<string | null>(null);
  const [selectedLeagueId, setSelectedLeagueId] = useState<number | null>(null);
  const [seasons, setSeasons] = useState<number[]>([]);
  const [seasonsStatus, setSeasonsStatus] = useState<LoadStatus>("loading");
  const [seasonsError, setSeasonsError] = useState<string | null>(null);
  const [season, setSeason] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [seasonsAttempt, setSeasonsAttempt] = useState(0);
  const [dataVersion, setDataVersion] = useState(0);

  const userId = user?.id ?? null;

  useEffect(() => {
    if (userId === null) {
      setLeagues([]);
      setLeaguesStatus("ready");
      setSelectedLeagueId(null);
      return;
    }
    const controller = new AbortController();
    setLeaguesStatus("loading");
    setLeaguesError(null);
    api.myLeagues(controller.signal).then(
      (memberships) => {
        setLeagues(memberships);
        setLeaguesStatus("ready");
        setSelectedLeagueId((current) => {
          if (current !== null && memberships.some((item) => item.league_id === current)) {
            return current;
          }
          return memberships[0]?.league_id ?? null;
        });
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setLeaguesStatus("error");
        setLeaguesError(error instanceof Error ? error.message : "Could not load your leagues.");
      },
    );
    return () => {
      controller.abort();
    };
  }, [userId, attempt]);

  useEffect(() => {
    if (selectedLeagueId === null) {
      setSeasons([]);
      setSeasonsStatus(leaguesStatus === "loading" ? "loading" : "ready");
      setSeasonsError(null);
      setSeason(null);
      return;
    }
    const controller = new AbortController();
    setSeasonsStatus("loading");
    setSeasonsError(null);
    api.seasons(selectedLeagueId, controller.signal).then(
      (response) => {
        setSeasons(response.seasons);
        setSeasonsStatus("ready");
        setSeason((current) =>
          current !== null && response.seasons.includes(current)
            ? current
            : latestSeason(response.seasons),
        );
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setSeasonsStatus("error");
        setSeasonsError(error instanceof Error ? error.message : "Could not load seasons.");
        setSeasons([]);
        setSeason(null);
      },
    );
    return () => {
      controller.abort();
    };
  }, [selectedLeagueId, leaguesStatus, seasonsAttempt]);

  const selectLeague = useCallback((leagueId: number) => {
    setSelectedLeagueId(leagueId);
  }, []);

  const selectSeason = useCallback(
    (next: number) => {
      if (seasons.includes(next)) {
        setSeason(next);
      }
    },
    [seasons],
  );

  const upsertLeague = useCallback((league: LeagueSummary) => {
    setLeagues((current) => {
      const existing = current.findIndex((item) => item.league_id === league.league_id);
      if (existing === -1) {
        return [...current, league];
      }
      const next = current.slice();
      next[existing] = league;
      return next;
    });
    setSelectedLeagueId(league.league_id);
  }, []);

  const reloadLeagues = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  const reloadSeasons = useCallback(() => {
    setSeasonsAttempt((current) => current + 1);
  }, []);

  const addStoredSeason = useCallback((added: number) => {
    setSeasons((current) =>
      current.includes(added) ? current : [...current, added].sort((a, b) => a - b),
    );
    setSeasonsStatus("ready");
    setSeasonsError(null);
    setSeason(added);
  }, []);

  const notifyDataChanged = useCallback(() => {
    setDataVersion((current) => current + 1);
  }, []);

  const selectedLeague = leagues.find((league) => league.league_id === selectedLeagueId) ?? null;

  const value = useMemo(
    () => ({
      leagues,
      leaguesStatus,
      leaguesError,
      selectedLeague,
      selectLeague,
      seasons,
      seasonsStatus,
      seasonsError,
      season,
      selectSeason,
      reloadSeasons,
      addStoredSeason,
      upsertLeague,
      reloadLeagues,
      dataVersion,
      notifyDataChanged,
    }),
    [
      leagues,
      leaguesStatus,
      leaguesError,
      selectedLeague,
      selectLeague,
      seasons,
      seasonsStatus,
      seasonsError,
      season,
      selectSeason,
      reloadSeasons,
      addStoredSeason,
      upsertLeague,
      reloadLeagues,
      dataVersion,
      notifyDataChanged,
    ],
  );

  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}
