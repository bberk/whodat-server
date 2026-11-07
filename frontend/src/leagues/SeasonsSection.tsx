import { useEffect, useState } from "react";

import { api } from "../api/endpoints";
import { toDisplayError } from "../api/errors";
import type { SeasonSettingsSummary } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/DataStates";
import { SortableHeader } from "../components/SortableHeader";
import {
  sortRows,
  toggleSort,
  type SortDirection,
  type SortState,
  type SortValue,
} from "../components/sorting";
import { LAST_ROW_NO_DIVIDER } from "../components/tableStyles";
import { secondaryButtonClass } from "../components/formStyles";
import { AddSeasonModal } from "./AddSeasonModal";
import { DeleteSeasonModal } from "./DeleteSeasonModal";
import { useLeague } from "./LeagueContext";
import { SeasonRow, type RowAction } from "./SeasonRow";

const headCell =
  "whitespace-nowrap border-b border-line bg-surface-muted px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-faint";
const stickyHead = "sticky left-0 z-20 min-w-[88px] bg-surface-muted shadow-sticky";

type SeasonsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; seasons: SeasonSettingsSummary[] };

type RowFlags = Readonly<Record<number, RowAction | undefined>>;
type RowMessages = Readonly<Record<number, string | undefined>>;

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

/** Numeric/date value for a sortable seasons column; a missing value sorts last. */
function sortValueFor(row: SeasonSettingsSummary, key: string): SortValue {
  switch (key) {
    case "season":
      return row.season;
    case "cup":
      return row.cup_week;
    case "refreshed": {
      if (row.last_refreshed_at === null) {
        return null;
      }
      const timestamp = Date.parse(row.last_refreshed_at);
      return Number.isNaN(timestamp) ? null : timestamp;
    }
    default:
      return null;
  }
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
  const [sort, setSort] = useState<SortState | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SeasonSettingsSummary | null>(null);

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
  const handleSort = (key: string, initialDirection: SortDirection) => {
    setSort((current) => toggleSort(current, key, initialDirection));
  };
  const orderedSeasons = sortRows(seasons, sort, sortValueFor);

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

  const handleAddSuccess = (newSeason: number) => {
    addStoredSeason(newSeason);
    reloadSeasons();
    setAddOpen(false);
    setActionMessage(`Season ${newSeason} added and synced.`);
    setAttempt((current) => current + 1);
    notifyDataChanged();
  };

  const handleDeleteSuccess = (deletedSeason: number) => {
    setState((current) => {
      if (current.status !== "ready") {
        return current;
      }
      const remaining = current.seasons.filter((item) => item.season !== deletedSeason);
      return remaining.length === 0 ? { status: "empty" } : { status: "ready", seasons: remaining };
    });
    setPendingDelete(null);
    setActionMessage(`Season ${deletedSeason} deleted.`);
    reloadSeasons();
    notifyDataChanged();
  };

  return (
    <section aria-labelledby="h-seasons" className="mt-7">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="h-seasons" className="text-base font-bold">
            Seasons
          </h2>
          <p className="mt-1 text-[13px] text-ink-faint">
            Refresh one season with your stored credentials, choose its cup week, or delete only
            that season&rsquo;s data.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
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
        <p role="status" className="mt-3 text-[13px] font-semibold text-ink-strong">
          {actionMessage}
        </p>
      )}

      {state.status === "ready" ? (
        <div
          className="mt-3 overflow-x-auto rounded-xl border border-line bg-surface"
          tabIndex={0}
          role="region"
          aria-label="Seasons, scrollable horizontally"
        >
          <table className="w-full min-w-[680px] border-separate border-spacing-0 text-left text-[13px]">
            <caption className="sr-only">
              Stored seasons for this league: season year, cup week, last refreshed time, refresh
              action, and delete action. Season year, cup week, and last refreshed are sortable.
            </caption>
            <thead>
              <tr>
                <SortableHeader
                  label="Season"
                  sortKey="season"
                  state={sort}
                  onSort={handleSort}
                  initialDirection="asc"
                  align="left"
                  className={`${headCell} ${stickyHead}`}
                />
                <SortableHeader
                  label="Cup week"
                  sortKey="cup"
                  state={sort}
                  onSort={handleSort}
                  initialDirection="asc"
                  align="left"
                  className={headCell}
                />
                <SortableHeader
                  label="Last refreshed"
                  sortKey="refreshed"
                  state={sort}
                  onSort={handleSort}
                  initialDirection="desc"
                  align="left"
                  className={headCell}
                />
                <th scope="col" className={headCell}>
                  Refresh
                </th>
                <th scope="col" className={headCell}>
                  Delete
                </th>
              </tr>
            </thead>
            <tbody className={LAST_ROW_NO_DIVIDER}>
              {orderedSeasons.map((row) => (
                <SeasonRow
                  key={row.season}
                  row={row}
                  busyAction={busy[row.season]}
                  errorMessage={errors[row.season]}
                  noticeMessage={notices[row.season]}
                  onSaveCupWeek={(r, week) => {
                    void saveCupWeek(r, week);
                  }}
                  onRefresh={(r) => {
                    void refreshSeason(r);
                  }}
                  onDelete={(r) => {
                    setPendingDelete(r);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <AddSeasonModal
        leagueId={leagueId}
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSuccess={handleAddSuccess}
      />

      <DeleteSeasonModal
        leagueId={leagueId}
        season={pendingDelete}
        onClose={() => setPendingDelete(null)}
        onSuccess={handleDeleteSuccess}
      />
    </section>
  );
}
