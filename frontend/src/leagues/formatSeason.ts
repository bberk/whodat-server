/**
 * Formatting helpers for the admin seasons table.
 *
 * The API sends `last_refreshed_at` as an ISO UTC instant (or null). A missing value means the
 * season has never synced through the provider; the UI shows "Never" rather than an empty cell.
 */
export function formatLastRefreshed(value: string | null): string {
  if (value === null) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Never";
  }
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
