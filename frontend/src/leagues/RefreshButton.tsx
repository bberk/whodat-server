import { useState } from "react";

import { api } from "../api/endpoints";
import { toDisplayError, type DisplayError } from "../api/errors";
import { secondaryButtonClass } from "../components/formStyles";

function syncedLabel(weeks: readonly number[]): string {
  if (weeks.length === 0) {
    return "Refresh finished; no weeks needed syncing.";
  }
  return `Refreshed ${weeks.length} week${weeks.length === 1 ? "" : "s"} (${weeks
    .map((week) => `W${week}`)
    .join(", ")}).`;
}

/**
 * Trigger a league-wide refresh. The control is disabled unless the selected membership holds
 * credentials (AC-AU-09); a 429 response shows the server's Retry-After window.
 */
export function RefreshButton({
  leagueId,
  hasCredentials,
  onRefreshed,
}: {
  leagueId: number | null;
  hasCredentials: boolean;
  onRefreshed: () => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<DisplayError | null>(null);

  const disabled = leagueId === null || !hasCredentials || refreshing;

  const refresh = async () => {
    if (leagueId === null) {
      return;
    }
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.refreshLeague(leagueId);
      setMessage(syncedLabel(result.weeks_synced));
      onRefreshed();
    } catch (failure) {
      setError(toDisplayError(failure));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => {
          void refresh();
        }}
        disabled={disabled}
        title={
          hasCredentials
            ? "Fetch the latest data from ESPN"
            : "This membership has no ESPN credentials, so it cannot refresh"
        }
        className={secondaryButtonClass}
      >
        {refreshing ? "Refreshing…" : "Refresh"}
      </button>
      {refreshing ? (
        <span role="status" className="text-[12.5px] text-gray-600">
          Refreshing league data…
        </span>
      ) : null}
      {error === null ? null : (
        <span role="alert" className="text-[12.5px] text-red-800">
          {error.message}
        </span>
      )}
      {error === null && message !== null ? (
        <span role="status" className="text-[12.5px] text-gray-600">
          {message}
        </span>
      ) : null}
      {!hasCredentials ? (
        <span className="text-[12px] text-gray-500">Refresh needs ESPN credentials.</span>
      ) : null}
    </div>
  );
}
