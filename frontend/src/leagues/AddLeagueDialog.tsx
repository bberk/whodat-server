import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { AddLeagueRequest } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ApiAlert } from "../components/ApiAlert";
import {
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../components/formStyles";
import { useLeague } from "./LeagueContext";

const MIN_SEASON = 2000;
const MAX_SEASON = 2100;

/**
 * Add (admin) or join (member) a league by ESPN league id.
 *
 * Credential fields render only for admins; a member joins an existing league without credentials.
 * The form validates locally first, then shows the API's structured error, including a 429 retry
 * window and 422 field messages.
 */
export function AddLeagueDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const { upsertLeague, notifyDataChanged } = useLeague();
  const [leagueId, setLeagueId] = useState("");
  const [season, setSeason] = useState("");
  const [espnS2, setEspnS2] = useState("");
  const [espnSwid, setEspnSwid] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<DisplayError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (open) {
      setLeagueId("");
      setSeason("");
      setEspnS2("");
      setEspnSwid("");
      setFormError(null);
      setApiError(null);
      setSubmitting(false);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const validate = (): AddLeagueRequest | null => {
    const trimmedId = leagueId.trim();
    if (trimmedId === "") {
      setFormError("Enter an ESPN league id.");
      return null;
    }
    const payload: AddLeagueRequest = { espn_league_id: trimmedId };
    if (season.trim() !== "") {
      const parsed = Number(season);
      if (!Number.isInteger(parsed) || parsed < MIN_SEASON || parsed > MAX_SEASON) {
        setFormError(`Season must be a whole year between ${MIN_SEASON} and ${MAX_SEASON}.`);
        return null;
      }
      payload.season = parsed;
    }
    if (isAdmin) {
      const hasS2 = espnS2.trim() !== "";
      const hasSwid = espnSwid.trim() !== "";
      if (hasS2 !== hasSwid) {
        setFormError("Enter both ESPN_S2 and ESPN_SWID, or neither.");
        return null;
      }
      if (hasS2 && hasSwid) {
        payload.espn_s2 = espnS2;
        payload.espn_swid = espnSwid;
      }
    }
    return payload;
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setApiError(null);
    const payload = validate();
    if (payload === null) {
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.addLeague(payload);
      upsertLeague(result.league);
      notifyDataChanged();
      onClose();
    } catch (failure) {
      setApiError(toDisplayError(failure));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-gray-900/40 p-4 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-league-title"
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="add-league-title" className="text-lg font-bold">
              Add a league
            </h2>
            <p className="mt-1 text-[13px] text-gray-500">
              {isAdmin
                ? "Add an ESPN league and optionally store credentials for private leagues."
                : "Join a league an admin has already added. Credentials are admin-only."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={secondaryButtonClass}
            aria-label="Close add-league dialog"
          >
            Close
          </button>
        </div>

        <form onSubmit={onSubmit} noValidate className="mt-4 space-y-4">
          <div>
            <label htmlFor="add-league-id" className={labelClass}>
              ESPN league id
            </label>
            <input
              id="add-league-id"
              name="espn_league_id"
              required
              value={leagueId}
              onChange={(event) => setLeagueId(event.target.value)}
              className={inputClass}
              placeholder="123456"
            />
          </div>
          <div>
            <label htmlFor="add-league-season" className={labelClass}>
              Season <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="add-league-season"
              name="season"
              type="number"
              min={MIN_SEASON}
              max={MAX_SEASON}
              value={season}
              onChange={(event) => setSeason(event.target.value)}
              className={inputClass}
              placeholder="2026"
            />
          </div>

          {isAdmin ? (
            <fieldset className="rounded-lg border border-gray-200 p-3">
              <legend className="px-1 text-[13px] font-semibold text-gray-700">
                ESPN credentials (optional)
              </legend>
              <div className="space-y-3">
                <div>
                  <label htmlFor="add-league-s2" className={labelClass}>
                    ESPN_S2
                  </label>
                  <input
                    id="add-league-s2"
                    name="espn_s2"
                    type="password"
                    autoComplete="off"
                    value={espnS2}
                    onChange={(event) => setEspnS2(event.target.value)}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label htmlFor="add-league-swid" className={labelClass}>
                    ESPN_SWID
                  </label>
                  <input
                    id="add-league-swid"
                    name="espn_swid"
                    type="password"
                    autoComplete="off"
                    value={espnSwid}
                    onChange={(event) => setEspnSwid(event.target.value)}
                    className={inputClass}
                  />
                </div>
              </div>
            </fieldset>
          ) : null}

          {formError === null ? null : (
            <p role="alert" className="text-[13px] text-red-800">
              {formError}
            </p>
          )}
          <ApiAlert error={apiError} />

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={secondaryButtonClass}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} className={primaryButtonClass}>
              {submitting ? "Adding…" : isAdmin ? "Add league" : "Join league"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
