import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { AddLeagueRequest } from "../api/types";
import { AuthLayout } from "../auth/AuthLayout";
import { useAuth } from "../auth/AuthContext";
import { ApiAlert } from "../components/ApiAlert";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";

const MIN_SEASON = 2000;
const MAX_SEASON = 2100;

/** The current calendar year, used as the default ESPN season. */
function currentSeason(): number {
  return new Date().getFullYear();
}

/**
 * Mandatory create-your-league step for an account that signed up with an admin invite (AC-AU-14).
 *
 * The account supplies its ESPN league id, season, and both cookies. A successful add stores the
 * league and membership server-side; `refreshUser()` then flips `has_league` so the gate opens and
 * the browser lands on the new league's standings. Until it succeeds, every other protected route
 * redirects back here. Credential values live only in this form's state: they are never logged,
 * echoed in an error, or rendered again after submitting.
 */
export function OnboardingPage() {
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [leagueId, setLeagueId] = useState("");
  const [season, setSeason] = useState(String(currentSeason()));
  const [espnS2, setEspnS2] = useState("");
  const [espnSwid, setEspnSwid] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<DisplayError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const validate = (): AddLeagueRequest | null => {
    const trimmedId = leagueId.trim();
    if (trimmedId === "") {
      setFormError("Enter your ESPN league id.");
      return null;
    }
    const parsedSeason = Number(season);
    if (
      season.trim() === "" ||
      !Number.isInteger(parsedSeason) ||
      parsedSeason < MIN_SEASON ||
      parsedSeason > MAX_SEASON
    ) {
      setFormError(`Season must be a whole year between ${MIN_SEASON} and ${MAX_SEASON}.`);
      return null;
    }
    if (espnS2.trim() === "" || espnSwid.trim() === "") {
      setFormError("Enter both ESPN_S2 and ESPN_SWID.");
      return null;
    }
    return {
      espn_league_id: trimmedId,
      season: parsedSeason,
      espn_s2: espnS2.trim(),
      espn_swid: espnSwid.trim(),
    };
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
      await api.addLeague(payload);
      await refreshUser();
      navigate("/", { replace: true });
    } catch (failure) {
      setApiError(toDisplayError(failure));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Add your ESPN league"
      subtitle={
        user === null
          ? "Your account has no league yet. Add the one you want to follow to see its standings."
          : `Signed in as ${user.email}. Add the ESPN league you want to follow to see its standings.`
      }
      footer={
        <>
          Wrong account?{" "}
          <button
            type="button"
            onClick={() => void logout()}
            className="font-semibold text-brand hover:underline"
          >
            Log out
          </button>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div>
          <label htmlFor="onboarding-league-id" className={labelClass}>
            ESPN league id
          </label>
          <input
            id="onboarding-league-id"
            name="espn_league_id"
            required
            autoComplete="off"
            value={leagueId}
            onChange={(event) => setLeagueId(event.target.value)}
            className={inputClass}
            placeholder="123456"
            aria-describedby="onboarding-league-id-note"
          />
          <p id="onboarding-league-id-note" className="mt-1 text-xs text-gray-500">
            The number in the ESPN league URL after <span className="font-mono">leagueId=</span>.
          </p>
        </div>

        <div>
          <label htmlFor="onboarding-season" className={labelClass}>
            Season
          </label>
          <input
            id="onboarding-season"
            name="season"
            type="number"
            inputMode="numeric"
            min={MIN_SEASON}
            max={MAX_SEASON}
            step={1}
            required
            value={season}
            onChange={(event) => setSeason(event.target.value)}
            className={inputClass}
            aria-describedby="onboarding-season-note"
          />
          <p id="onboarding-season-note" className="mt-1 text-xs text-gray-500">
            The year the league played, from {MIN_SEASON} to {MAX_SEASON}. Defaults to the current
            year.
          </p>
        </div>

        <fieldset
          aria-describedby="onboarding-credentials-note"
          className="rounded-lg border border-gray-200 p-3"
        >
          <legend className="px-1 text-[13px] font-semibold text-gray-700">ESPN credentials</legend>
          <div className="space-y-3">
            <div>
              <label htmlFor="onboarding-s2" className={labelClass}>
                ESPN_S2
              </label>
              <input
                id="onboarding-s2"
                name="espn_s2"
                type="password"
                autoComplete="off"
                required
                value={espnS2}
                onChange={(event) => setEspnS2(event.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="onboarding-swid" className={labelClass}>
                ESPN_SWID
              </label>
              <input
                id="onboarding-swid"
                name="espn_swid"
                type="password"
                autoComplete="off"
                required
                value={espnSwid}
                onChange={(event) => setEspnSwid(event.target.value)}
                className={inputClass}
              />
            </div>
          </div>
          <p id="onboarding-credentials-note" className="mt-3 text-xs text-gray-500">
            Find both cookies in your browser&rsquo;s developer tools under Application &rarr;
            Cookies on espn.com. They are stored encrypted and are never shown again.
          </p>
        </fieldset>

        {formError === null ? null : (
          <p role="alert" className="text-[13px] text-red-800">
            {formError}
          </p>
        )}
        <ApiAlert error={apiError} />

        <button type="submit" disabled={submitting} className={`${primaryButtonClass} w-full`}>
          {submitting ? "Adding your league…" : "Add league and continue"}
        </button>
      </form>
    </AuthLayout>
  );
}
