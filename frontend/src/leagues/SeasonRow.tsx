import type { SeasonSettingsSummary } from "../api/types";
import {
  dangerSecondaryButtonClass,
  secondaryButtonClass,
  selectClass,
} from "../components/formStyles";
import { BODY_CELL_DIVIDER_SUBTLE } from "../components/tableStyles";
import { formatLastRefreshed } from "./formatSeason";

const bodyCell = `${BODY_CELL_DIVIDER_SUBTLE} px-3 py-2 align-middle`;
const stickyBody = "sticky left-0 z-10 min-w-[88px] bg-surface shadow-sticky";

export type RowAction = "cup" | "refresh" | "delete";

export interface SeasonRowProps {
  row: SeasonSettingsSummary;
  busyAction?: RowAction;
  errorMessage?: string;
  noticeMessage?: string;
  onSaveCupWeek: (row: SeasonSettingsSummary, cupWeek: number | null) => void;
  onRefresh: (row: SeasonSettingsSummary) => void;
  onDelete: (row: SeasonSettingsSummary) => void;
}

export function SeasonRow({
  row,
  busyAction,
  errorMessage,
  noticeMessage,
  onSaveCupWeek,
  onRefresh,
  onDelete,
}: SeasonRowProps) {
  const isBusy = busyAction !== undefined;
  const hasMessage = errorMessage !== undefined || noticeMessage !== undefined;

  return (
    <>
      <tr>
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
            disabled={isBusy}
            onChange={(event) => {
              const value = event.target.value === "" ? null : Number(event.target.value);
              onSaveCupWeek(row, value);
            }}
          >
            <option value="">No cup week</option>
            {Array.from({ length: row.regular_season_length }, (_, index) => index + 1).map(
              (week) => (
                <option key={week} value={week}>
                  Week {week}
                </option>
              ),
            )}
          </select>
          {busyAction === "cup" ? (
            <span className="ml-2 text-[12px] text-ink-subtle">Saving…</span>
          ) : null}
        </td>
        <td className={bodyCell}>
          <span className="whitespace-nowrap">{formatLastRefreshed(row.last_refreshed_at)}</span>
        </td>
        <td className={bodyCell}>
          <button
            type="button"
            onClick={() => onRefresh(row)}
            disabled={isBusy}
            aria-label={`Refresh season ${row.season}`}
            className={secondaryButtonClass}
          >
            {busyAction === "refresh" ? "Refreshing…" : "Refresh"}
          </button>
        </td>
        <td className={bodyCell}>
          <button
            type="button"
            onClick={() => onDelete(row)}
            disabled={isBusy}
            aria-label={`Delete season ${row.season}`}
            title={`Delete season ${row.season}`}
            className={dangerSecondaryButtonClass}
          >
            <span aria-hidden="true">×</span>
          </button>
        </td>
      </tr>
      {hasMessage ? (
        <tr>
          <td colSpan={5} className={`${BODY_CELL_DIVIDER_SUBTLE} px-3 py-2`}>
            {errorMessage !== undefined ? (
              <p role="alert" className="text-[12.5px] text-danger-ink">
                {errorMessage}
              </p>
            ) : (
              <p role="status" className="text-[12.5px] text-ink-subtle">
                {noticeMessage}
              </p>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}
