import { useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import { inputClass, labelClass, primaryButtonClass } from "../components/formStyles";
import { useLeague } from "./LeagueContext";

const MIN_SEASON = 2000;
const MAX_SEASON = 2100;

function currentYear(): number {
  return new Date().getFullYear();
}

/**
 * Admin: add and sync another season for an existing league (AC-AU-18, AC-FE-10).
 *
 * The year is validated as a whole number in the supported range before the request, so an empty
 * or malformed value never reaches the API. The call uses the caller's own stored credentials on
 * the server. On success the shared season list is refreshed and the new season becomes selected,
 * so the standings view follows immediately. Success and failure are announced as text, never by
 * colour alone.
 */
export function AddSeasonSection({ leagueId }: { leagueId: number }) {
  const { addStoredSeason, reloadSeasons } = useLeague();
  const [year, setYear] = useState(String(currentYear()));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<DisplayError | null>(null);
  const [added, setAdded] = useState<number | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setApiError(null);
    setAdded(null);

    const trimmed = year.trim();
    const parsed = Number(trimmed);
    if (trimmed === "" || !Number.isInteger(parsed)) {
      setFormError(`Enter a whole season year between ${MIN_SEASON} and ${MAX_SEASON}.`);
      return;
    }
    if (parsed < MIN_SEASON || parsed > MAX_SEASON) {
      setFormError(`Season must be a whole year between ${MIN_SEASON} and ${MAX_SEASON}.`);
      return;
    }

    setSaving(true);
    try {
      const response = await api.addSeason(leagueId, { season: parsed });
      addStoredSeason(response.season);
      reloadSeasons();
      setAdded(response.season);
    } catch (failure) {
      setApiError(toDisplayError(failure));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-labelledby="h-add-season" className="mt-7 max-w-lg">
      <h2 id="h-add-season" className="text-base font-bold">
        Add a season
      </h2>
      <p className="mt-1 text-[13px] text-gray-500">
        Sync another season for this league using your stored credentials.
      </p>

      <form
        onSubmit={onSubmit}
        noValidate
        className="mt-3 rounded-xl border border-gray-200 bg-white p-4"
      >
        <label htmlFor="add-season-year" className={labelClass}>
          Season year
        </label>
        <input
          id="add-season-year"
          name="season"
          type="number"
          inputMode="numeric"
          min={MIN_SEASON}
          max={MAX_SEASON}
          step={1}
          required
          value={year}
          onChange={(event) => setYear(event.target.value)}
          className={inputClass}
          disabled={saving}
          aria-describedby="add-season-year-note"
        />
        <p id="add-season-year-note" className="mt-1 text-xs text-gray-500">
          A whole year from {MIN_SEASON} to {MAX_SEASON}.
        </p>

        {formError === null ? null : (
          <p role="alert" className="mt-3 text-[13px] text-red-800">
            {formError}
          </p>
        )}
        <ApiAlert error={apiError} />

        {saving ? (
          <p role="status" className="mt-3 text-[13px] text-gray-700">
            Adding and syncing season…
          </p>
        ) : null}
        {added === null ? null : (
          <p role="status" className="mt-3 text-[13px] font-semibold text-brand">
            Season {added} added and synced.
          </p>
        )}

        <div className="mt-4 flex justify-end">
          <button type="submit" disabled={saving} className={primaryButtonClass}>
            {saving ? "Adding…" : "Add season"}
          </button>
        </div>
      </form>
    </section>
  );
}
