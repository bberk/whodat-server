import { useCallback, useEffect, useState } from "react";

import { api } from "../api/endpoints";
import type { WapdateResponse } from "../api/types";

export type WapdateState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; wapdate: WapdateResponse };

export interface WapdateData {
  state: WapdateState;
  reload: () => void;
}

/**
 * Load the WAPDate periods for the selected league and season, exposing the four states a data
 * view must handle: loading, error, empty (no offered periods yet), and ready. `reload` re-runs
 * the request; a stale response is ignored once the effect has been torn down.
 */
export function useWapdateData(
  leagueId: number | null,
  season: number | null,
  dataVersion: number,
): WapdateData {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<WapdateState>({ status: "loading" });

  useEffect(() => {
    if (leagueId === null || season === null) {
      setState({ status: "loading" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    api.wapdate(leagueId, season, controller.signal).then(
      (wapdate) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(wapdate.periods.length === 0 ? { status: "empty" } : { status: "ready", wapdate });
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
