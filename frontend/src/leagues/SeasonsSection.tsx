import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import type { SeasonSettingsSummary } from "../api/types";
import { ApiAlert } from "../components/ApiAlert";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import {
  dangerSecondaryButtonClass,
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
  selectClass,
} from "../components/formStyles";
import { useLeague } from "./LeagueContext";
import { formatLastRefreshed } from "./formatSeason";

const MIN_SEASON = 2000;
const MAX_SEASON = 2100;

const headCell =
  "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500";
const bodyCell = "px-3 py-2 align-middle";
const stickyHead =
  "sticky left-0 z-20 min-w-[88px] bg-gray-50 shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]";
const stickyBody =
  "sticky left-0 z-10 min-w-[88px] bg-white shadow-[6px_0_8px_-6px_rgba(17,24,39,0.18)]";

type SeasonsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; seasons: SeasonSettingsSummary[] };

type RowAction = "cup" | "refresh" | "delete";

type RowFlags = Readonly<Record<number, RowAction | undefined>>;
type RowMessages = Readonly<Record<number, string | undefined>>;

function currentYear(): number {
  return new Date().getFullYear();
}

function syncedLabel(weeks: readonly number[]): string {
  if (weeks.length === 0) {
    return "Refresh finished; no weeks needed syncing.";
  }
  return `Refreshed ${weeks.length} week${weeks.length === 1 ? "" : "s"} (${weeks
    .map((week) => `W${week}`)
    .join(", ")}).`;
}

function withoutKey(flags: RowFlags, season: number): RowFlags {
  const next = { ...flags };
  delete next[season];
  return next;
}

function withKey(flags: RowFlags, season: number, action: RowAction): RowFlags {
  return { ...flags, [season]: action };
}

function messageWithout(messages: RowMessages, season: number): RowMessages {
  return { ...messages, [season]: undefined };
}

function messageWith(messages: RowMessages, season: number, message: string): RowMessages {
  return { ...messages, [season]: message };
}

/**
 * Admin: every stored season in one table (AC-FE-16).
 *
 * Each row offers the season's cup week (saved immediately through the provider-free cup-week
 * route), a refresh that syncs only that season through the provider with the caller's stored
 * credentials, and a confirmed delete that removes only that season's data. The "+" action adds
 * and syncs another season. Every action reports its own loading, success, and error text; nothing
 * depends on colour alone, and the season column stays pinned while the table scrolls on a phone.
 */
export function SeasonsSection({ leagueId }: { leagueId: number }) {
  const { addStoredSeason, reloadSeasons, notifyDataChanged } = useLeague();
  const [state, setState] = useState<SeasonsState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<RowFlags>({});
  const [errors, setErrors] = useState<RowMessages>({});
  const [notices, setNotices] = useState<RowMessages>({});
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [year, setYear] = useState(String(currentYear()));
  const [addSaving, setAddSaving] = useState(false);
  const [addFormError, setAddFormError] = useState<string | null>(null);
  const [addError, setAddError] = useState<DisplayError | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SeasonSettingsSummary | null>(null);
  const [deleteError, setDeleteError] = useState<DisplayError | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    api.seasonSettings(leagueId, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          response.seasons.length === 0
            ? { status: "empty" }
            : { status: "ready", seasons: response.seasons },
        );
      },
      (failure: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          message: failure instanceof Error ? failure.message : "Could not load seasons.",
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [leagueId, attempt]);

  const seasons = state.status === "ready" ? state.seasons : [];

  const updateRow = (season: number, patch: Partial<SeasonSettingsSummary>) => {
    setState((current) =>
      current.status === "ready"
        ? {
            status: "ready",
            seasons: current.seasons.map((row) =>
              row.season === season ? { ...row, ...patch } : row,
            ),
          }
        : current,
    );
  };

  const clearRowMessages = (season: number) => {
    setErrors((current) => messageWithout(current, season));
    setNotices((current) => messageWithout(current, season));
  };

  const saveCupWeek = async (row: SeasonSettingsSummary, cupWeek: number | null) => {
    if (row.cup_week === cupWeek) {
      return;
    }
    setBusy((current) => withKey(current, row.season, "cup"));
    clearRowMessages(row.season);
    setActionMessage(null);
    try {
      const response = await api.updateCupWeek(leagueId, row.season, { cup_week: cupWeek });
      updateRow(row.season, { cup_week: response.cup_week });
      setNotices((current) =>
        messageWith(current, row.season, `Cup week saved for ${row.season}.`),
      );
      notifyDataChanged();
    } catch (failure) {
      setErrors((current) => messageWith(current, row.season, toDisplayError(failure).message));
    } finally {
      setBusy((current) => withoutKey(current, row.season));
    }
  };

  const refreshSeason = async (row: SeasonSettingsSummary) => {
    setBusy((current) => withKey(current, row.season, "refresh"));
    clearRowMessages(row.season);
    setActionMessage(null);
    try {
      const result = await api.refreshSeason(leagueId, row.season);
      updateRow(row.season, { last_refreshed_at: new Date().toISOString() });
      setNotices((current) => messageWith(current, row.season, syncedLabel(result.weeks_synced)));
      notifyDataChanged();
    } catch (failure) {
      setErrors((current) => messageWith(current, row.season, toDisplayError(failure).message));
    } finally {
      setBusy((current) => withoutKey(current, row.season));
    }
  };

  const closeAdd = () => {
    if (addSaving) {
      return;
    }
    setAddOpen(false);
    setAddFormError(null);
    setAddError(null);
  };

  const submitAdd = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAddFormError(null);
    setAddError(null);
    const trimmed = year.trim();
    const parsed = Number(trimmed);
    if (trimmed === "" || !Number.isInteger(parsed)) {
      setAddFormError(`Enter a whole season year between ${MIN_SEASON} and ${MAX_SEASON}.`);
      return;
    }
    if (parsed < MIN_SEASON || parsed > MAX_SEASON) {
      setAddFormError(`Season must be a whole year between ${MIN_SEASON} and ${MAX_SEASON}.`);
      return;
    }
    setAddSaving(true);
    try {
      const response = await api.addSeason(leagueId, { season: parsed });
      addStoredSeason(response.season);
      reloadSeasons();
      setAddOpen(false);
      setActionMessage(`Season ${response.season} added and synced.`);
      setAttempt((current) => current + 1);
      notifyDataChanged();
    } catch (failure) {
      setAddError(toDisplayError(failure));
    } finally {
      setAddSaving(false);
    }
  };

  const closeDelete = () => {
    if (pendingDelete !== null && busy[pendingDelete.season] === "delete") {
      return;
    }
    setDeleteError(null);
    setPendingDelete(null);
  };

  const confirmDelete = async () => {
    if (pendingDelete === null) {
      return;
    }
    const row = pendingDelete;
    setBusy((current) => withKey(current, row.season, "delete"));
    setDeleteError(null);
    try {
      await api.deleteSeason(leagueId, row.season);
      setState((current) => {
        if (current.status !== "ready") {
          return current;
        }
        const remaining = current.seasons.filter((item) => item.season !== row.season);
        return remaining.length === 0
          ? { status: "empty" }
          : { status: "ready", seasons: remaining };
      });
      setPendingDelete(null);
      setActionMessage(`Season ${row.season} deleted.`);
      reloadSeasons();
      notifyDataChanged();
    } catch (failure) {
      setDeleteError(toDisplayError(failure));
    } finally {
      setBusy((current) => withoutKey(current, row.season));
    }
  };

  const deleting = pendingDelete !== null && busy[pendingDelete.season] === "delete";

  return (
    <section aria-labelledby="h-seasons" className="mt-7">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="h-seasons" className="text-base font-bold">
            Seasons
          </h2>
          <p className="mt-1 text-[13px] text-gray-500">
            Refresh one season with your stored credentials, choose its cup week, or delete only
            that season&rsquo;s data.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setAddFormError(null);
            setAddError(null);
            setYear(String(currentYear()));
            setAddOpen(true);
          }}
          aria-label="Add a season"
          title="Add a season"
          className={secondaryButtonClass}
        >
          +
        </button>
      </div>

      {state.status === "loading" ? <LoadingState label="Loading seasons…" /> : null}

      {state.status === "error" ? (
        <ErrorState onRetry={() => setAttempt((current) => current + 1)} message={state.message} />
      ) : null}

      {state.status === "empty" ? (
        <EmptyState
          title="No seasons yet"
          detail="Use + to add and sync a season with your stored credentials."
        />
      ) : null}

      {actionMessage === null ? null : (
        <p role="status" className="mt-3 text-[13px] font-semibold text-gray-800">
          {actionMessage}
        </p>
      )}

      {state.status === "ready" ? (
        <div className="mt-3 overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="w-full min-w-[680px] border-collapse text-left text-[13px]">
            <caption className="sr-only">
              Stored seasons for this league: season year, cup week, last refreshed time, refresh
              action, and delete action.
            </caption>
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th scope="col" className={`${headCell} ${stickyHead}`}>
                  Season
                </th>
                <th scope="col" className={headCell}>
                  Cup week
                </th>
                <th scope="col" className={headCell}>
                  Last refreshed
                </th>
                <th scope="col" className={headCell}>
                  Refresh
                </th>
                <th scope="col" className={headCell}>
                  Delete
                </th>
              </tr>
            </thead>
            <tbody>
              {seasons.map((row) => {
                const rowBusy = busy[row.season];
                const rowError = errors[row.season];
                const rowNotice = notices[row.season];
                return [
                  <tr key={row.season} className="border-b border-gray-100 last:border-0">
                    <th scope="row" className={`${bodyCell} font-semibold ${stickyBody}`}>
                      {row.season}
                    </th>
                    <td className={bodyCell}>
                      <label htmlFor={`cup-week-${row.season}`} className="sr-only">
                        Cup week for {row.season}
                      </label>
                      <select
                        id={`cup-week-${row.season}`}
                        className={selectClass}
                        value={row.cup_week ?? ""}
                        disabled={rowBusy !== undefined}
                        onChange={(event) => {
                          const value =
                            event.target.value === "" ? null : Number(event.target.value);
                          void saveCupWeek(row, value);
                        }}
                      >
                        <option value="">No cup week</option>
                        {Array.from(
                          { length: row.regular_season_length },
                          (_, index) => index + 1,
                        ).map((week) => (
                          <option key={week} value={week}>
                            Week {week}
                          </option>
                        ))}
                      </select>
                      {rowBusy === "cup" ? (
                        <span className="ml-2 text-[12px] text-gray-600">Saving…</span>
                      ) : null}
                    </td>
                    <td className={bodyCell}>
                      <span className="whitespace-nowrap">
                        {formatLastRefreshed(row.last_refreshed_at)}
                      </span>
                    </td>
                    <td className={bodyCell}>
                      <button
                        type="button"
                        onClick={() => {
                          void refreshSeason(row);
                        }}
                        disabled={rowBusy !== undefined}
                        aria-label={`Refresh season ${row.season}`}
                        className={secondaryButtonClass}
                      >
                        {rowBusy === "refresh" ? "Refreshing…" : "Refresh"}
                      </button>
                    </td>
                    <td className={bodyCell}>
                      <button
                        type="button"
                        onClick={() => {
                          setDeleteError(null);
                          setPendingDelete(row);
                        }}
                        disabled={rowBusy !== undefined}
                        aria-label={`Delete season ${row.season}`}
                        title={`Delete season ${row.season}`}
                        className={dangerSecondaryButtonClass}
                      >
                        <span aria-hidden="true">×</span>
                      </button>
                    </td>
                  </tr>,
                  rowError !== undefined || rowNotice !== undefined ? (
                    <tr key={`${row.season}-message`} className="border-b border-gray-100">
                      <td colSpan={5} className="px-3 py-2">
                        {rowError !== undefined ? (
                          <p role="alert" className="text-[12.5px] text-red-800">
                            {rowError}
                          </p>
                        ) : (
                          <p role="status" className="text-[12.5px] text-gray-600">
                            {rowNotice}
                          </p>
                        )}
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {addOpen ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-gray-900/40 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="h-add-season"
            className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl"
          >
            <h3 id="h-add-season" className="text-lg font-bold">
              Add a season
            </h3>
            <p className="mt-2 text-[13px] text-gray-600">
              Sync another season for this league using your stored credentials.
            </p>
            <form onSubmit={submitAdd} noValidate className="mt-3">
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
                disabled={addSaving}
                aria-describedby="add-season-year-note"
              />
              <p id="add-season-year-note" className="mt-1 text-xs text-gray-500">
                A whole year from {MIN_SEASON} to {MAX_SEASON}.
              </p>
              {addFormError === null ? null : (
                <p role="alert" className="mt-2 text-[13px] text-red-800">
                  {addFormError}
                </p>
              )}
              <ApiAlert error={addError} />
              {addSaving ? (
                <p role="status" className="mt-2 text-[13px] text-gray-700">
                  Adding and syncing season…
                </p>
              ) : null}
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={closeAdd}
                  disabled={addSaving}
                  className={secondaryButtonClass}
                  autoFocus
                >
                  Cancel
                </button>
                <button type="submit" disabled={addSaving} className={primaryButtonClass}>
                  {addSaving ? "Adding…" : "Add season"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {pendingDelete === null ? null : (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-gray-900/40 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="h-delete-season"
            className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl"
          >
            <h3 id="h-delete-season" className="text-lg font-bold">
              Delete season {pendingDelete.season}?
            </h3>
            <p className="mt-2 text-[13px] text-gray-600">
              This removes only the {pendingDelete.season} season&rsquo;s teams, matchups, and
              scores. The league, its owners, members, invites, and every other season stay.
            </p>
            {deleteError === null ? null : (
              <div className="mt-3">
                <ApiAlert error={deleteError} />
              </div>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeDelete}
                disabled={deleting}
                className={secondaryButtonClass}
                autoFocus
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  void confirmDelete();
                }}
                disabled={deleting}
                className={dangerSecondaryButtonClass}
              >
                {deleting ? "Deleting…" : `Delete season ${pendingDelete.season}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
