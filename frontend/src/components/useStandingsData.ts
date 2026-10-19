import { useCallback, useEffect, useState } from "react";

import type { StandingsBundle, StandingsSource } from "../mocks/standings";

export type StandingsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; bundle: StandingsBundle };

export interface StandingsData {
  state: StandingsState;
  reload: () => void;
}

/**
 * Load the standings bundle from an injected source and expose the four states a data view must
 * handle: loading, error, empty, and ready. `reload` re-runs the request (used by the retry
 * button); a stale response is ignored once the effect has been torn down.
 *
 * `source` must be stable across renders (for example a module constant or a `useMemo` value):
 * a new identity each render would restart the request in a loop.
 */
export function useStandingsData(source: StandingsSource): StandingsData {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<StandingsState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    source.load().then(
      (bundle) => {
        if (!active) {
          return;
        }
        setState(
          bundle.standings.overall.length === 0 ? { status: "empty" } : { status: "ready", bundle },
        );
      },
      (error: unknown) => {
        if (!active) {
          return;
        }
        setState({
          status: "error",
          message: error instanceof Error ? error.message : "The request failed",
        });
      },
    );
    return () => {
      active = false;
    };
  }, [source, attempt]);

  const reload = useCallback(() => {
    setAttempt((current) => current + 1);
  }, []);

  return { state, reload };
}
