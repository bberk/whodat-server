import { ariaSortFor, type SortDirection, type SortState } from "./sorting";

export interface SortableHeaderProps {
  /** Visible column label. It is also the button's accessible name unless `buttonLabel` is set. */
  label: string;
  /** Stable key passed back to the table's sort handler. */
  sortKey: string;
  state: SortState | null;
  onSort: (key: string, initialDirection: SortDirection) => void;
  /** First-click direction; repeat clicks toggle. */
  initialDirection?: SortDirection;
  /** Extra classes for the `<th>` (usually the table's shared header-cell classes). */
  className?: string;
  /** Align the button label to the left or right edge of the column. */
  align?: "left" | "right";
  /** Accessible name for the `<th>` when the visible label is an abbreviation such as "W1". */
  headerLabel?: string;
  /** Accessible name for the button; defaults to `Sort by <label>`. */
  buttonLabel?: string;
}

const DIRECTION_MARK = {
  ascending: "▲",
  descending: "▼",
  none: "↕",
} as const;

/**
 * A `<th scope="col">` whose contents are a keyboard-operable sort button.
 *
 * `aria-sort` lives on the header cell, so assistive technology hears the column's state without
 * the visible arrow (which is aria-hidden) changing the column's accessible name. Every header
 * starts at `aria-sort="none"`; the table keeps its API order until a numeric header is clicked.
 */
export function SortableHeader({
  label,
  sortKey,
  state,
  onSort,
  initialDirection = "desc",
  className,
  align = "right",
  headerLabel,
  buttonLabel,
}: SortableHeaderProps) {
  const sort = ariaSortFor(state, sortKey);
  const active = sort !== "none";
  const buttonName = buttonLabel ?? `Sort by ${label}`;
  return (
    <th scope="col" aria-sort={sort} aria-label={headerLabel} className={className}>
      <button
        type="button"
        onClick={() => onSort(sortKey, initialDirection)}
        aria-label={buttonName}
        title={buttonName}
        className={`inline-flex w-full items-center gap-1 rounded py-0.5 hover:text-gray-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
          align === "right" ? "justify-end text-right" : "justify-start text-left"
        }`}
      >
        <span>{label}</span>
        <span
          aria-hidden="true"
          className={`text-[9px] leading-none ${active ? "text-gray-700" : "text-gray-400"}`}
        >
          {DIRECTION_MARK[sort]}
        </span>
      </button>
    </th>
  );
}
