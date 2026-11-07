import { useEffect, useState } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { SeasonSettingsSummary } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import { dangerSecondaryButtonClass, secondaryButtonClass } from "../components/formStyles";

export interface DeleteSeasonModalProps {
  leagueId: number;
  season: SeasonSettingsSummary | null;
  onClose: () => void;
  onSuccess: (deletedSeason: number) => void;
}

export function DeleteSeasonModal({
  leagueId,
  season,
  onClose,
  onSuccess,
}: DeleteSeasonModalProps) {
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<DisplayError | null>(null);

  useEffect(() => {
    setDeleteError(null);
    setDeleting(false);
  }, [season]);

  if (season === null) {
    return null;
  }

  const handleClose = () => {
    if (deleting) {
      return;
    }
    setDeleteError(null);
    onClose();
  };

  const handleConfirm = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteSeason(leagueId, season.season);
      onSuccess(season.season);
    } catch (failure) {
      setDeleteError(toDisplayError(failure));
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-overlay/40 p-4 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="h-delete-season"
        className="w-full max-w-md rounded-xl border border-line bg-surface p-5 shadow-xl"
      >
        <h3 id="h-delete-season" className="text-lg font-bold">
          Delete season {season.season}?
        </h3>
        <p className="mt-2 text-[13px] text-ink-subtle">
          This removes only the {season.season} season&rsquo;s teams, matchups, and scores. The
          league, its owners, members, invites, and every other season stay.
        </p>
        {deleteError === null ? null : (
          <div className="mt-3">
            <ApiAlert error={deleteError} />
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={deleting}
            className={secondaryButtonClass}
            autoFocus
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              void handleConfirm();
            }}
            disabled={deleting}
            className={dangerSecondaryButtonClass}
          >
            {deleting ? "Deleting…" : `Delete season ${season.season}`}
          </button>
        </div>
      </div>
    </div>
  );
}
