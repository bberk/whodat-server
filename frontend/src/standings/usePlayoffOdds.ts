import { useCallback, useEffect, useState } from "react";

import { api } from "../api/endpoints";
import type { PlayoffOddsResponse } from "../api/types";

export type PlayoffOddsUnavailableReason = NonNullable<PlayoffOddsResponse["reason"]>;

export type PlayoffOddsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "unavailable"; reason: PlayoffOddsUnavailableReason; odds: PlayoffOddsResponse }
  | { status: "ready"; odds: PlayoffOddsResponse };

export interface PlayoffOddsData {
  state: PlayoffOddsState;
  reload: () => void;
}

/**
 * Load playoff odds for the selected league and season, exposing the states the section must
 * handle: loading, error, unavailable (with the API's reason), and ready. `reload` re-runs the
 * request; a stale response is ignored once the effect has been torn down.
 */
export function usePlayoffOdds(
  leagueId: number | null,
  season: number | null,
  dataVersion: number,
): PlayoffOddsData {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PlayoffOddsState>({ status: "loading" });

  useEffect(() => {
    if (leagueId === null || season === null) {
      setState({ status: "loading" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    api.playoffOdds(leagueId, season, { signal: controller.signal }).then(
      (odds) => {
        if (controller.signal.aborted) {
          return;
        }
        if (odds.status === "unavailable" && odds.reason !== null) {
          setState({ status: "unavailable", reason: odds.reason, odds });
          return;
        }
        setState({ status: "ready", odds });
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "The request failed",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [leagueId, season, dataVersion, attempt]);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return { state, reload };
}
