import { useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import { dangerButtonClass, inputClass, labelClass } from "../components/formStyles";

interface DeleteLeagueSectionProps {
  leagueId: number;
  leagueName: string;
  /** Called after the server deletes the league so the shell can refresh and leave the page. */
  onDeleted: () => void;
}

/**
 * Admin: delete this league and all of its data, behind a typed-name confirmation (AC-AU-22).
 *
 * The league name must be typed exactly before the destructive button enables. The copy spells out
 * that only this league's rows go (seasons, teams, owners, matchups, scores, memberships, and
 * invites bound to it) while accounts, league-less admin invites, and other leagues remain. The
 * parent refreshes the league list and returns to the standings afterwards.
 */
export function DeleteLeagueSection({ leagueId, leagueName, onDeleted }: DeleteLeagueSectionProps) {
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<DisplayError | null>(null);

  const confirmed = confirmation.trim() === leagueName;

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!confirmed || deleting) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await api.deleteLeague(leagueId);
      setConfirmation("");
      onDeleted();
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section
      aria-labelledby="h-danger-zone"
      className="mt-9 rounded-xl border-2 border-red-300 bg-red-50 p-4 md:p-5"
    >
      <h2 id="h-danger-zone" className="text-base font-bold text-red-900">
        Danger zone: delete this league
      </h2>
      <p className="mt-1 text-[13px] text-gray-700">
        Deleting <span className="font-semibold">{leagueName}</span> permanently removes this league
        and all of its data: seasons, teams, owners, matchups, scores, memberships, and invites
        bound to it. Accounts, league-less admin invites, and your other leagues are not affected.
      </p>
      <p className="mt-2 text-[13px] font-semibold text-red-900">This cannot be undone.</p>

      <form onSubmit={onSubmit} noValidate className="mt-3 max-w-lg">
        <label htmlFor="delete-league-name" className={labelClass}>
          Type the league name to confirm
        </label>
        <input
          id="delete-league-name"
          name="league_name"
          autoComplete="off"
          required
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          className={inputClass}
          disabled={deleting}
          aria-describedby="delete-league-name-note"
        />
        <p id="delete-league-name-note" className="mt-1 text-xs text-gray-600">
          Type <span className="font-mono font-semibold">{leagueName}</span> exactly.
        </p>

        <ApiAlert error={error} />

        {deleting ? (
          <p role="status" className="mt-3 text-[13px] text-gray-800">
            Deleting the league…
          </p>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button type="submit" disabled={!confirmed || deleting} className={dangerButtonClass}>
            {deleting ? "Deleting…" : "Delete league permanently"}
          </button>
        </div>
      </form>
    </section>
  );
}
