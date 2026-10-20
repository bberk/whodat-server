import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

/**
 * Run axe on the current page and fail on serious or critical violations.
 *
 * The message names the rule, its impact, and the affected selectors so a CI failure points at the
 * element instead of only an opaque count.
 */
export async function expectNoBlockingAxeViolations(page: Page, pageName: string): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  const detail = blocking
    .map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.help}\n` +
        violation.nodes.map((node) => `  ${node.target.join(" ")}`).join("\n"),
    )
    .join("\n");
  expect(
    blocking.map((violation) => violation.id),
    `${pageName} axe violations:\n${detail}`,
  ).toEqual([]);
}
