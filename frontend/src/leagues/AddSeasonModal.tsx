import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import {
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "../components/formStyles";

const MIN_SEASON = 2000;
const MAX_SEASON = 2100;

function currentYear(): number {
  return new Date().getFullYear();
}

export interface AddSeasonModalProps {
  leagueId: number;
  open: boolean;
  onClose: () => void;
  onSuccess: (season: number) => void;
}

export function AddSeasonModal({ leagueId, open, onClose, onSuccess }: AddSeasonModalProps) {
  const [year, setYear] = useState(String(currentYear()));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<DisplayError | null>(null);

  useEffect(() => {
    if (open) {
      setYear(String(currentYear()));
      setFormError(null);
      setApiError(null);
      setSaving(false);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const handleClose = () => {
    if (saving) {
      return;
    }
    setFormError(null);
    setApiError(null);
    onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    setApiError(null);
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
      onSuccess(response.season);
    } catch (failure) {
      setApiError(toDisplayError(failure));
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-overlay/40 p-4 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="h-add-season"
        className="w-full max-w-md rounded-xl border border-line bg-surface p-5 shadow-xl"
      >
        <h3 id="h-add-season" className="text-lg font-bold">
          Add a season
        </h3>
        <p className="mt-2 text-[13px] text-ink-subtle">
          Sync another season for this league using your stored credentials.
        </p>
        <form onSubmit={handleSubmit} noValidate className="mt-3">
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
          <p id="add-season-year-note" className="mt-1 text-xs text-ink-faint">
            A whole year from {MIN_SEASON} to {MAX_SEASON}.
          </p>
          {formError === null ? null : (
            <p role="alert" className="mt-2 text-[13px] text-danger-ink">
              {formError}
            </p>
          )}
          <ApiAlert error={apiError} />
          {saving ? (
            <p role="status" className="mt-2 text-[13px] text-ink-muted">
              Adding and syncing season…
            </p>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={saving}
              className={secondaryButtonClass}
              autoFocus
            >
              Cancel
            </button>
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Adding…" : "Add season"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
