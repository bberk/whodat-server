import { useCallback, useEffect, useState } from "react";

import { api } from "../api/endpoints";
import type { EloHistoryResponse } from "../api/types";
import type { EloMode } from "./model";

export type EloHistoryState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; history: EloHistoryResponse };

export interface EloHistoryData {
  state: EloHistoryState;
  reload: () => void;
}

/**
 * Load Elo history for the selected league and mode.
 *
 * Switching mode refetches; `dataVersion` lets the admin settings action invalidate every history
 * view after a save. A response with no rated weeks is surfaced as the empty state. A stale
 * response is ignored once its request has been aborted.
 */
export function useEloHistory(
  leagueId: number | null,
  mode: EloMode,
  dataVersion: number,
): EloHistoryData {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<EloHistoryState>({ status: "loading" });

  useEffect(() => {
    if (leagueId === null) {
      setState({ status: "loading" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    api.eloHistory(leagueId, mode, controller.signal).then(
      (history) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          history.teams.length === 0 || history.weeks.length === 0
            ? { status: "empty" }
            : { status: "ready", history },
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
  }, [leagueId, mode, dataVersion, attempt]);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return { state, reload };
}
