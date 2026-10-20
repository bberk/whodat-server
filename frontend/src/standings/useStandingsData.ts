import { useCallback, useEffect, useState } from "react";

import { api } from "../api/endpoints";
import type { StandingsResponse, VpHistoryResponse } from "../api/types";

export type StandingsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; standings: StandingsResponse; history: VpHistoryResponse };

export interface StandingsData {
  state: StandingsState;
  reload: () => void;
}

/**
 * Load standings and VP history for the selected league and season, exposing the four states a
 * data view must handle: loading, error, empty, and ready. `reload` re-runs both requests (used by
 * the retry button); a stale response is ignored once the effect has been torn down.
 */
export function useStandingsData(
  leagueId: number | null,
  season: number | null,
  dataVersion: number,
): StandingsData {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<StandingsState>({ status: "loading" });

  useEffect(() => {
    if (leagueId === null || season === null) {
      setState({ status: "loading" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    Promise.all([
      api.standings(leagueId, season, controller.signal),
      api.vpHistory(leagueId, season, controller.signal),
    ]).then(
      ([standings, history]) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          standings.overall.length === 0
            ? { status: "empty" }
            : { status: "ready", standings, history },
        );
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
