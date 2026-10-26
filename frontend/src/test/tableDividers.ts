import { expect } from "vitest";

/**
 * Asserts a table paints its row divider on every body cell, including the final column, and
 * removes it from the last row through `<tbody>` rather than through a per-cell `last:` selector.
 */
export function expectRowDividersAcrossEveryCell(table: HTMLElement): void {
  const tbody = table.querySelector("tbody");
  expect(tbody).not.toBeNull();
  expect(tbody?.className).toContain("[&>tr:last-child>*]:border-b-0");

  const rows = Array.from(tbody?.querySelectorAll(":scope > tr") ?? []);
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    const cells = Array.from(row.children) as HTMLElement[];
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.className).toContain("border-b");
      expect(cell.className).toMatch(/\bborder-line(?:-subtle)?\b/);
    }
    const finalCell = cells[cells.length - 1];
    expect(finalCell.className).toContain("border-b");
    expect(finalCell.className).toMatch(/\bborder-line(?:-subtle)?\b/);
  }
}
