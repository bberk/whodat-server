import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { OwnerSummary } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { primaryButtonClass, secondaryButtonClass, selectClass } from "../components/formStyles";
import { useLeague } from "../leagues/LeagueContext";

type OwnersState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; owners: OwnerSummary[] };

/**
 * Associate the caller's own membership with one of the league's owners (AC-AU-12).
 *
 * The page lists the owners the server offers, saves through `PUT /me/leagues/{id}/owner`, and
 * reflects the updated membership in the shared league list so the rest of the shell stays fresh.
 */
export function OwnerPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague, upsertLeague } = useLeague();
  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);

  const [ownersState, setOwnersState] = useState<OwnersState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [ownerId, setOwnerId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<DisplayError | null>(null);
  const [saved, setSaved] = useState(false);
  const membershipOwnerId = membership?.owner_id ?? null;
  const membershipLeagueId = membership?.league_id ?? null;

  useEffect(() => {
    if (validId && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, leagueId, selectedLeague?.league_id, selectLeague]);

  useEffect(() => {
    if (membershipLeagueId !== null) {
      setOwnerId(membershipOwnerId);
    }
  }, [membershipOwnerId, membershipLeagueId]);

  useEffect(() => {
    if (!validId) {
      setOwnersState({ status: "error", message: "This league id is not valid." });
      return;
    }
    const controller = new AbortController();
    setOwnersState({ status: "loading" });
    api.owners(leagueId, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) {
          return;
        }
        setOwnersState(
          response.owners.length === 0
            ? { status: "empty" }
            : { status: "ready", owners: response.owners },
        );
      },
      (failure: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setOwnersState({
          status: "error",
          message: failure instanceof Error ? failure.message : "Could not load owners.",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [validId, leagueId, attempt]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validId) {
      return;
    }
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const response = await api.setOwner(leagueId, { owner_id: ownerId });
      upsertLeague(response.league);
      setSaved(true);
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setSaving(false);
    }
  };

  const leagueName = membership?.name ?? `League ${validId ? leagueId : ""}`;

  return (
    <div className="pt-5 md:pt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold md:text-2xl">Owner · {leagueName}</h1>
          <p className="mt-1 text-[13px] text-ink-faint">
            Choose the team you own in this league. This only changes your own membership.
          </p>
        </div>
        <Link to="/" className={`${secondaryButtonClass}`}>
          Back to standings
        </Link>
      </div>

      <section aria-labelledby="h-owner" className="mt-7 max-w-lg">
        <h2 id="h-owner" className="text-base font-bold">
          Your team
        </h2>

        {ownersState.status === "loading" ? <LoadingState label="Loading owners…" /> : null}

        {ownersState.status === "error" ? (
          <ErrorState
            onRetry={() => setAttempt((current) => current + 1)}
            message={ownersState.message}
          />
        ) : null}

        {ownersState.status === "empty" ? (
          <EmptyState
            title="No owners yet"
            detail="Owners appear after the league data has been synced. An admin can refresh the season from the league admin page."
          />
        ) : null}

        {ownersState.status === "ready" ? (
          <form onSubmit={submit} className="mt-3 rounded-xl border border-line bg-surface p-4">
            <label
              htmlFor="owner-select"
              className="block text-[13px] font-semibold text-ink-muted"
            >
              Owner
            </label>
            <select
              id="owner-select"
              className={`${selectClass} mt-1 w-full`}
              value={ownerId ?? ""}
              onChange={(event) =>
                setOwnerId(event.target.value === "" ? null : Number(event.target.value))
              }
              disabled={saving}
            >
              <option value="">Unassigned</option>
              {ownersState.owners.map((owner) => (
                <option key={owner.id} value={owner.id}>
                  {owner.display_name}
                </option>
              ))}
            </select>

            {error === null ? null : (
              <p role="alert" className="mt-3 text-[13px] text-danger-ink">
                {error.message}
              </p>
            )}
            {saved ? (
              <p role="status" className="mt-3 text-[13px] text-brand-ink">
                Owner saved.
              </p>
            ) : null}

            <div className="mt-4 flex justify-end">
              <button type="submit" disabled={saving} className={primaryButtonClass}>
                {saving ? "Saving…" : "Save owner"}
              </button>
            </div>
          </form>
        ) : null}
      </section>
    </div>
  );
}
