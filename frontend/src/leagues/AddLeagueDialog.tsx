import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { AddLeagueRequest } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ApiAlert } from "../components/ApiAlert";
import { asciiOnlyMessage } from "../components/formValidation";
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
 * Admin: add a league by ESPN league id with optional credentials.
 * Member: join a league with the invite code its admin shared.
 *
 * Admins may add any league (no invite); members can only join through a valid member invite, so
 * the member form is a single code field and never offers credentials or a bare league id. The
 * invite code and the cookies are never logged or echoed back; API failures show the server's
 * structured message, including a 429 retry window and 422 field messages.
 */
export function AddLeagueDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const { upsertLeague, notifyDataChanged } = useLeague();
  const [leagueId, setLeagueId] = useState("");
  const [season, setSeason] = useState("");
  const [espnS2, setEspnS2] = useState("");
  const [espnSwid, setEspnSwid] = useState("");
  const [inviteCode, setInviteCode] = useState("");
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
      setInviteCode("");
      setFormError(null);
      setApiError(null);
      setSubmitting(false);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const validateLeague = (): AddLeagueRequest | null => {
    const trimmedId = leagueId.trim();
    if (trimmedId === "") {
      setFormError("Enter an ESPN league id.");
      return null;
    }
    const idAsciiError = asciiOnlyMessage("ESPN league id", trimmedId);
    if (idAsciiError !== null) {
      setFormError(idAsciiError);
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
    const hasS2 = espnS2.trim() !== "";
    const hasSwid = espnSwid.trim() !== "";
    if (hasS2 !== hasSwid) {
      setFormError("Enter both ESPN_S2 and ESPN_SWID, or neither.");
      return null;
    }
    const credentialAsciiError =
      asciiOnlyMessage("ESPN_S2", espnS2.trim()) ?? asciiOnlyMessage("ESPN_SWID", espnSwid.trim());
    if (credentialAsciiError !== null) {
      setFormError(credentialAsciiError);
      return null;
    }
    if (hasS2 && hasSwid) {
      payload.espn_s2 = espnS2.trim();
      payload.espn_swid = espnSwid.trim();
    }
    return payload;
  };

  const addLeague = async () => {
    const payload = validateLeague();
    if (payload === null) {
      return;
    }
    const result = await api.addLeague(payload);
    upsertLeague(result.league);
    notifyDataChanged();
    onClose();
  };

  const redeemInvite = async () => {
    const code = inviteCode.trim();
    if (code === "") {
      setFormError("Enter an invite code.");
      return;
    }
    const codeAsciiError = asciiOnlyMessage("Invite code", code);
    if (codeAsciiError !== null) {
      setFormError(codeAsciiError);
      return;
    }
    const result = await api.redeemInvite({ invite_code: code });
    upsertLeague(result.league);
    notifyDataChanged();
    onClose();
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setApiError(null);
    setSubmitting(true);
    try {
      if (isAdmin) {
        await addLeague();
      } else {
        await redeemInvite();
      }
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
        aria-labelledby="league-dialog-title"
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="league-dialog-title" className="text-lg font-bold">
              {isAdmin ? "Add a league" : "Join a league"}
            </h2>
            <p className="mt-1 text-[13px] text-gray-500">
              {isAdmin
                ? "Add an ESPN league and optionally store credentials for private leagues."
                : "Enter the member invite code from your league admin. Joining needs no credentials."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={secondaryButtonClass}
            aria-label={isAdmin ? "Close add-league dialog" : "Close join-league dialog"}
          >
            Close
          </button>
        </div>

        <form onSubmit={onSubmit} noValidate className="mt-4 space-y-4">
          {isAdmin ? (
            <>
              <div>
                <label htmlFor="add-league-id" className={labelClass}>
                  ESPN league id
                </label>
                <input
                  id="add-league-id"
                  name="espn_league_id"
                  inputMode="text"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  pattern="[A-Za-z0-9._-]+"
                  maxLength={64}
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
                  inputMode="numeric"
                  min={MIN_SEASON}
                  max={MAX_SEASON}
                  step={1}
                  value={season}
                  onChange={(event) => setSeason(event.target.value)}
                  className={inputClass}
                  placeholder="2026"
                />
              </div>
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
            </>
          ) : (
            <div>
              <label htmlFor="join-invite-code" className={labelClass}>
                Invite code
              </label>
              <input
                id="join-invite-code"
                name="invite_code"
                type="password"
                autoComplete="off"
                inputMode="text"
                autoCapitalize="none"
                spellCheck={false}
                pattern="[A-Za-z0-9_-]+"
                maxLength={128}
                required
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
                className={inputClass}
                aria-describedby="join-invite-code-note"
              />
              <p id="join-invite-code-note" className="mt-1 text-xs text-gray-500">
                The code is checked once and is never shown again.
              </p>
            </div>
          )}

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
              {isAdmin
                ? submitting
                  ? "Adding…"
                  : "Add league"
                : submitting
                  ? "Joining…"
                  : "Join league"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
