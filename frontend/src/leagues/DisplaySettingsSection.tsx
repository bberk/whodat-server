import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { ApiAlert } from "../components/ApiAlert";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { primaryButtonClass } from "../components/formStyles";
import { useLeague } from "./LeagueContext";

/**
 * Admin: per-league display preferences (AC-API-11, AC-FE-20).
 *
 * The WAPDate four-week worst-team view is a quirk not every league uses, so an admin can hide it
 * from the standings page. The flag ships with the league list, so this section reads its value
 * from the shared context and needs no GET request. Saving PUTs the value, replaces the cached
 * league through `upsertLeague` (the standings page reads that flag and drops the section without
 * requesting `/wapdate`), and keeps an unsaved choice on screen when the save fails.
 */
export function DisplaySettingsSection({ leagueId }: { leagueId: number }) {
  const { leagues, leaguesStatus, leaguesError, selectedLeague, reloadLeagues, upsertLeague } =
    useLeague();
  const league =
    leagues.find((item) => item.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);
  const [draft, setDraft] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [failure, setFailure] = useState<DisplayError | null>(null);

  useEffect(() => {
    setDraft(null);
    setSaving(false);
    setSuccess(null);
    setFailure(null);
  }, [leagueId]);

  const storedValue = league?.show_wapdate ?? true;
  const value = draft ?? storedValue;

  const select = (next: boolean) => {
    setDraft(next);
    setSuccess(null);
    setFailure(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (league === null) {
      return;
    }
    setSaving(true);
    setFailure(null);
    setSuccess(null);
    try {
      const updated = await api.updateDisplaySettings(leagueId, { show_wapdate: value });
      upsertLeague(updated);
      setDraft(null);
      setSuccess(
        updated.show_wapdate
          ? "WAPDate standings section shown on the standings page."
          : "WAPDate standings section hidden from the standings page.",
      );
    } catch (error) {
      // Keep the chosen value so the admin can retry without re-entering it.
      setFailure(toDisplayError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-labelledby="h-display-settings" className="mt-7">
      <h2 id="h-display-settings" className="text-base font-bold">
        Display settings
      </h2>
      <p className="mt-1 text-[13px] text-ink-faint">
        Per league · controls which optional sections the standings page shows.
      </p>

      {leaguesStatus === "loading" ? <LoadingState label="Loading display settings…" /> : null}

      {leaguesStatus === "error" ? (
        <ErrorState
          onRetry={reloadLeagues}
          message={leaguesError ?? "Could not load your leagues."}
        />
      ) : null}

      {leaguesStatus === "ready" && league === null ? (
        <EmptyState
          title="League not found"
          detail="This league is not in your league list. Reload your leagues and try again."
        />
      ) : null}

      {leaguesStatus === "ready" && league !== null ? (
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          className="mt-3 rounded-xl border border-line bg-surface p-4"
        >
          <div className="flex items-start gap-3">
            <input
              id="display-show-wapdate"
              name="show_wapdate"
              type="checkbox"
              checked={value}
              onChange={(event) => select(event.target.checked)}
              aria-describedby="display-show-wapdate-hint"
              disabled={saving}
              className="mt-0.5 h-4 w-4 shrink-0 accent-brand-ink"
            />
            <div className="min-w-0">
              <label
                htmlFor="display-show-wapdate"
                className="block text-[13px] font-semibold text-ink"
              >
                WAPDate standings
              </label>
              <p id="display-show-wapdate-hint" className="mt-1 text-xs text-ink-faint">
                Show the four-week worst-team section on the standings page. Some leagues do not use
                this quirk; turning it off hides the section and stops the page requesting its data.
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                {value
                  ? "The standings page shows this section."
                  : "The standings page hides this section."}
              </p>
            </div>
          </div>

          {failure === null ? null : (
            <div className="mt-3">
              <ApiAlert error={failure} />
            </div>
          )}
          {success === null ? null : (
            <p role="status" className="mt-3 text-[13px] font-semibold text-ink-strong">
              {success}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button type="submit" disabled={saving} className={primaryButtonClass}>
              {saving ? "Saving…" : "Save display settings"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
