/**
 * Row dividers for the app's tables.
 *
 * Tailwind binds `last:` to the last compound selector it wraps, so a per-cell divider removal
 * under `last:` compiled to `td:last-child` and dropped the divider under the final column of
 * every row. Instead, every body cell paints its own divider and `<tbody>` removes it from its
 * final row, where the rounded container already draws the bottom edge.
 */
export const BODY_CELL_DIVIDER = "border-b border-line";
export const BODY_CELL_DIVIDER_SUBTLE = "border-b border-line-subtle";
export const LAST_ROW_NO_DIVIDER = "[&>tr:last-child>*]:border-b-0";
