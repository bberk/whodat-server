import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { ErrorState, LoadingState } from "../components/DataStates";
import { labelClass, primaryButtonClass, selectClass } from "../components/formStyles";

type CupWeekState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; current: number | null; regularSeasonLength: number };

interface CupWeekSectionProps {
  leagueId: number;
  season: number;
}

/**
 * Choose a season's optional cup week (SPEC 3.4, AC-FE-11).
 *
 * The section reads `GET .../seasons/{season}/cup-week`, offers `No cup week` plus weeks
 * 1..regular_season_length from the server, and saves through the matching `PUT`. A saved change
 * is confirmed with text in a `status` region, never by colour alone. The parent page owns the
 * admin route guard; this component assumes the caller may read the season.
 */
export function CupWeekSection({ leagueId, season }: CupWeekSectionProps) {
  const [state, setState] = useState<CupWeekState>({ status: "loading" });
  const [draft, setDraft] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<DisplayError | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    setError(null);
    setSaved(false);
    api.cupWeek(leagueId, season, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "ready",
          current: response.cup_week,
          regularSeasonLength: response.regular_season_length,
        });
        setDraft(response.cup_week);
      },
      (failure: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          message: failure instanceof Error ? failure.message : "Could not load the cup week.",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [leagueId, season, attempt]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (state.status !== "ready") {
      return;
    }
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const response = await api.updateCupWeek(leagueId, season, { cup_week: draft });
      setState({
        status: "ready",
        current: response.cup_week,
        regularSeasonLength: response.regular_season_length,
      });
      setDraft(response.cup_week);
      setSaved(true);
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-labelledby="h-cup-week" className="mt-7 w-full max-w-lg">
      <h2 id="h-cup-week" className="text-base font-bold">
        Cup week
      </h2>
      <p className="mt-1 text-[13px] text-gray-500">
        On a cup week there is no head-to-head VP and no W-L-T change. High score, top half, worst
        score, and points for still count.
      </p>

      {state.status === "loading" ? <LoadingState label="Loading cup week…" /> : null}

      {state.status === "error" ? (
        <ErrorState onRetry={() => setAttempt((current) => current + 1)} message={state.message} />
      ) : null}

      {state.status === "ready" ? (
        <form onSubmit={submit} className="mt-3 rounded-xl border border-gray-200 bg-white p-4">
          <label htmlFor="cup-week-select" className={labelClass}>
            Cup week for this season
          </label>
          <select
            id="cup-week-select"
            className={`${selectClass} mt-1 w-full`}
            value={draft ?? ""}
            onChange={(event) =>
              setDraft(event.target.value === "" ? null : Number(event.target.value))
            }
            disabled={saving}
          >
            <option value="">No cup week</option>
            {Array.from({ length: state.regularSeasonLength }, (_, index) => index + 1).map(
              (week) => (
                <option key={week} value={week}>
                  Week {week}
                </option>
              ),
            )}
          </select>

          {error === null ? null : (
            <div role="alert" className="mt-3 text-[13px] text-red-800">
              <p>{error.message}</p>
              {Object.values(error.fieldErrors).map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          )}
          {saved ? (
            <p role="status" className="mt-3 text-[13px] font-semibold text-gray-800">
              Cup week saved. Standings will show the updated VP.
            </p>
          ) : null}

          <div className="mt-4 flex justify-end">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Saving…" : "Save cup week"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
