import { expect, test, type Page } from "@playwright/test";

import fixture from "../../e2e/fixture.json" with { type: "json" };
import { expectNoBlockingAxeViolations } from "./axe";

/** Run this whole file with the operating system reporting a dark colour scheme. */
test.use({ colorScheme: "dark" });

const THEME_STORAGE_KEY = "vp-theme";

async function expectPageDoesNotScrollSideways(page: Page): Promise<void> {
  const width = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(width.scrollWidth, "the page body must not scroll horizontally").toBeLessThanOrEqual(
    width.clientWidth,
  );
}

/**
 * Dark-mode smoke journey: a first visit follows the OS preference with no flash of light, an
 * explicit choice overrides it and survives reloads, the signed-in surfaces (including the pinned
 * table columns) render dark, and both the auth page and the standings pass axe at the project's
 * viewport width.
 */
test("follows the OS theme, persists an explicit choice, and stays accessible in dark mode", async ({
  page,
}, testInfo) => {
  const root = page.locator("html");
  const storedTheme = () => page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY);

  // First visit: the OS prefers dark and no explicit choice exists yet.
  await page.goto("/login");
  await expect(root).toHaveClass(/dark/);
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("radio", { name: "System" })).toBeChecked();
  await expectNoBlockingAxeViolations(page, "login (dark)");
  await expectPageDoesNotScrollSideways(page);

  // An explicit Light choice overrides the OS preference and survives a reload.
  await page.getByText("Light", { exact: true }).click();
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked();
  await expect(root).not.toHaveClass(/dark/);
  expect(await storedTheme()).toBe("light");
  await page.reload();
  await expect(root).not.toHaveClass(/dark/);
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked();

  // An explicit Dark choice survives a reload too.
  await page.getByText("Dark", { exact: true }).click();
  await page.reload();
  await expect(root).toHaveClass(/dark/);
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  expect(await storedTheme()).toBe("dark");

  // Sign in and read the seeded standings with the dark surfaces applied.
  await page.getByLabel("Email", { exact: true }).fill(fixture.users.admin.email);
  await page.getByLabel("Password", { exact: true }).fill(fixture.users.admin.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(fixture.league.name) }),
  ).toBeVisible();

  const overall = page.getByRole("region", {
    name: "Overall standings, scrollable horizontally",
  });
  await expect(overall).toBeVisible();
  await expect(overall.getByRole("columnheader", { name: "Team" })).toBeVisible();
  await expect(page.getByRole("img", { name: /cumulative victory points/i })).toBeVisible();

  // The pinned team column stays sticky and keeps an opaque dark background (no bleed-through).
  const teamHeader = overall.getByRole("columnheader", { name: "Team" });
  expect(await teamHeader.evaluate((element) => getComputedStyle(element).position)).toBe("sticky");
  const headerBackground = await teamHeader.evaluate(
    (element) => getComputedStyle(element).backgroundColor,
  );
  expect(headerBackground).not.toBe("rgba(0, 0, 0, 0)");
  expect(headerBackground).not.toBe("transparent");
  expect(headerBackground).not.toBe("rgb(255, 255, 255)");

  await expectPageDoesNotScrollSideways(page);
  await expectNoBlockingAxeViolations(page, "standings (dark)");

  // Returning to System follows the (dark) OS preference again and clears the stored value.
  await page.getByText("System", { exact: true }).click();
  await expect(root).toHaveClass(/dark/);
  await expect(page.getByRole("radio", { name: "System" })).toBeChecked();
  expect(await storedTheme()).toBeNull();

  await testInfo.attach(`standings-dark-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
