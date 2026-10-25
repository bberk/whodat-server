/**
 * Client-side sorting for the data tables.
 *
 * Only numeric or date-derived columns are sortable; text columns (team, owner, email) stay in API
 * order so the client can never invent a different ordering for identity fields. Sorting is stable:
 * rows with equal values keep their original order, which is the API's rank/current order, and the
 * API rank value itself is never rewritten. Missing values always sort last in both directions.
 */

export type SortDirection = "asc" | "desc";

export interface SortState {
  key: string;
  direction: SortDirection;
}

/** A comparable cell value; `null`/`undefined` (and an empty date string) sort last. */
export type SortValue = number | string | null | undefined;

/** Return the state a click on `key` should produce: first click uses `initial`, repeat clicks toggle. */
export function toggleSort(
  current: SortState | null,
  key: string,
  initial: SortDirection,
): SortState {
  if (current !== null && current.key === key) {
    return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  }
  return { key, direction: initial };
}

function isMissing(value: SortValue): value is null | undefined | "" {
  return value === null || value === undefined || value === "";
}

function comparePresent(left: number | string, right: number | string): number {
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return String(left).localeCompare(String(right));
}

/**
 * Sort a copy of `rows` for `state`, reading each row's value through `valueFor`.
 *
 * `valueFor` receives the sort key so one table can sort dynamic columns (weekly VP). Rows whose
 * value is missing go last regardless of direction; equal values keep API order. A `null` state
 * returns the rows in API order untouched.
 */
export function sortRows<T>(
  rows: readonly T[],
  state: SortState | null,
  valueFor: (row: T, key: string) => SortValue,
): T[] {
  if (state === null) {
    return rows.slice();
  }
  const direction = state.direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: valueFor(row, state.key) }))
    .sort((left, right) => {
      const leftMissing = isMissing(left.value);
      const rightMissing = isMissing(right.value);
      if (leftMissing && rightMissing) {
        return left.index - right.index;
      }
      if (leftMissing) {
        return 1;
      }
      if (rightMissing) {
        return -1;
      }
      const comparison = comparePresent(
        left.value as number | string,
        right.value as number | string,
      );
      if (comparison === 0) {
        return left.index - right.index;
      }
      return comparison * direction;
    })
    .map((entry) => entry.row);
}

/** The value for a `<th aria-sort>`: only the column being sorted reports a direction. */
export function ariaSortFor(
  state: SortState | null,
  key: string,
): "ascending" | "descending" | "none" {
  if (state === null || state.key !== key) {
    return "none";
  }
  return state.direction === "asc" ? "ascending" : "descending";
}
