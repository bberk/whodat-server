import { expect, test, type Locator, type Page } from "@playwright/test";

import fixture from "../../e2e/fixture.json" with { type: "json" };
import { expectNoBlockingAxeViolations } from "./axe";
import { expectReadableChart } from "./eloChartChecks";

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

/** The resolved token backgrounds used by the pinned cells in each theme. */
const THEME_BACKGROUNDS = {
  dark: {
    surface: "rgb(17, 26, 43)",
    hover: "rgb(26, 37, 59)",
    selected: "rgb(16, 49, 47)",
    header: "rgb(23, 34, 54)",
  },
  light: {
    surface: "rgb(255, 255, 255)",
    hover: "rgb(249, 250, 251)",
    selected: "rgb(240, 253, 250)",
    header: "rgb(249, 250, 251)",
  },
} as const;

interface PinnedCellStyle {
  position: string;
  backgroundColor: string;
  alpha: number;
  left: number;
  right: number;
  width: number;
}

/** Read the computed background and geometry of a sticky cell in the live page. */
async function readPinnedCell(cell: Locator): Promise<PinnedCellStyle> {
  return cell.evaluate((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const channels = style.backgroundColor.match(/[\d.]+/g)?.map(Number) ?? [];
    return {
      position: style.position,
      backgroundColor: style.backgroundColor,
      alpha: channels.length === 4 ? channels[3] : 1,
      left: rect.left,
      right: rect.right,
      width: rect.width,
    };
  });
}

/**
 * A pinned cell must stay sticky and paint a fully opaque token, otherwise the horizontally
 * scrolled columns show through it.
 */
async function expectOpaquePinnedCell(
  cell: Locator,
  label: string,
  background: string,
): Promise<PinnedCellStyle> {
  const style = await readPinnedCell(cell);
  expect(style.position, `${label} must stay pinned`).toBe("sticky");
  expect(style.alpha, `${label} must have an opaque background`).toBe(1);
  expect(style.backgroundColor, `${label} must use its row-state token`).toBe(background);
  return style;
}

/**
 * Assert the Elo table's pinned rank and team cells paint an opaque token in every row state, and
 * that the rank cell fills exactly the offset the team cell pins by, with the table scrolled to its
 * end so the other columns sit underneath them.
 */
async function expectEloPinnedTableOpaque(
  page: Page,
  theme: keyof typeof THEME_BACKGROUNDS,
): Promise<void> {
  const backgrounds = THEME_BACKGROUNDS[theme];
  const region = page.getByRole("region", {
    name: "Elo score history current scores, scrollable horizontally",
  });
  const headerRank = region.locator("thead th").nth(0);
  const headerTeam = region.locator("thead th").nth(1);
  const firstRow = region.locator("tbody tr").first();
  const rank = firstRow.locator("th").first();
  const team = firstRow.locator("td").first();

  // Scroll the wide table fully so other columns sit underneath the pinned ones.
  await region.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  const scroll = await region.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  expect(scroll.scrollWidth, "the Elo table must scroll at 360px").toBeGreaterThan(
    scroll.clientWidth,
  );

  await expectOpaquePinnedCell(headerRank, "Elo header rank", backgrounds.header);
  await expectOpaquePinnedCell(headerTeam, "Elo header team", backgrounds.header);
  const normalRank = await expectOpaquePinnedCell(rank, "Elo rank", backgrounds.surface);
  const normalTeam = await expectOpaquePinnedCell(team, "Elo team", backgrounds.surface);
  expect(
    Math.abs(normalRank.right - normalTeam.left),
    "the pinned team cell must start where the rank cell ends",
  ).toBeLessThanOrEqual(1);
  expect(normalRank.width, "the rank cell must keep the 44px pinned offset").toBeGreaterThanOrEqual(
    43,
  );

  await firstRow.getByRole("button").hover();
  await expectOpaquePinnedCell(rank, "hovered Elo rank", backgrounds.hover);
  await expectOpaquePinnedCell(team, "hovered Elo team", backgrounds.hover);

  await firstRow.getByRole("button").click();
  await expect(firstRow.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  await expectOpaquePinnedCell(rank, "selected Elo rank", backgrounds.selected);
  await expectOpaquePinnedCell(team, "selected Elo team", backgrounds.selected);
  await firstRow.getByRole("button").click();
  await expect(firstRow.getByRole("button")).toHaveAttribute("aria-pressed", "false");
}

/** The resolved `ink-faint` token a hidden VP legend chip must paint in each theme (>= 4.5:1). */
const HIDDEN_VP_CHIP_COLORS = {
  dark: "rgb(142, 160, 182)",
  light: "rgb(107, 114, 128)",
} as const;

/**
 * Hide the first VP series from the chart legend and prove its dimmed state is still readable.
 *
 * The chip only dims after a click, so no static page scan sees it. axe checks the built CSS for
 * contrast, and the computed colour pins the AA-compliant `ink-faint` token so a dimmed token
 * cannot creep back in even where axe's own contrast heuristic might miss it.
 */
async function expectHiddenVpSeriesIsAccessible(
  page: Page,
  theme: keyof typeof HIDDEN_VP_CHIP_COLORS,
): Promise<void> {
  const chip = page.getByRole("list", { name: "Chart series toggles" }).getByRole("button").first();
  const label = await chip.getAttribute("title");
  await chip.click();
  await expect(chip, "the legend chip toggles to hidden").toHaveAttribute("aria-pressed", "false");
  await expect(chip, "the hidden chip keeps the line-through cue").toHaveClass(/line-through/);
  await expectNoBlockingAxeViolations(page, `standings with a hidden VP series (${theme})`);
  expect(
    await chip.evaluate((element) => getComputedStyle(element).color),
    `the hidden chip (${label}) must use the contrast-safe ink-faint token in ${theme}`,
  ).toBe(HIDDEN_VP_CHIP_COLORS[theme]);
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
}

/**
 * Dark-mode smoke journey: a first visit follows the OS preference with no flash of light, an
 * explicit choice overrides it and survives reloads, the signed-in surfaces render dark, and axe
 * passes at the project's viewport width on the auth page, the standings, History, Admin, a modal
 * dialog, and the VP legend's hidden state — in both themes, since a token can fail only on one.
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

  // AC-PO-11/19: the odds table and its controls are present in dark mode; as an admin the
  // iteration maximum is 100,000.
  const odds = page.getByRole("region", {
    name: "Playoff odds, scrollable horizontally",
  });
  await expect(odds).toBeVisible();
  await expect(odds.getByRole("columnheader", { name: "Championship %" })).toBeVisible();
  await expect(page.getByLabel("Simulations", { exact: true })).toHaveValue("10000");
  await expect(page.getByText(/Use 1 to 100,000 simulations/i)).toBeVisible();

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

  // The VP legend's hidden state only exists after a click, so no static scan can see it.
  await expectHiddenVpSeriesIsAccessible(page, "dark");

  // The rest of the signed-in surfaces: History (Elo chart, controls, current-scores table) and
  // Admin (members, Elo settings, seasons), plus a modal dialog that is hidden until it opens.
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await expect(page.getByRole("heading", { level: 2, name: "Current scores" })).toBeVisible();
  await expectNoBlockingAxeViolations(page, "history (dark)");
  await expectPageDoesNotScrollSideways(page);
  await expectReadableChart(
    page,
    "dark",
    testInfo,
    fixture.teams.map((team) => team.name),
    "seeded",
  );

  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", { level: 1, name: "League admin" })).toBeVisible();
  await expectNoBlockingAxeViolations(page, "league admin (dark)");

  await page.getByRole("button", { name: "Add league" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a league" });
  await expect(dialog).toBeVisible();
  await expectNoBlockingAxeViolations(page, "add-league dialog (dark)");
  await dialog.getByRole("button", { name: "Close add-league dialog" }).click();
  await expect(dialog).toHaveCount(0);

  // The light theme must pass the same scans, including the hidden chip on its white surface.
  await page.getByText("Light", { exact: true }).click();
  await expect(root).not.toHaveClass(/dark/);
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await expectReadableChart(
    page,
    "light",
    testInfo,
    fixture.teams.map((team) => team.name),
    "seeded",
  );
  await page.getByRole("link", { name: "Standings", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expectHiddenVpSeriesIsAccessible(page, "light");
  await expectPageDoesNotScrollSideways(page);

  // Returning to System follows the (dark) OS preference again and clears the stored value.
  await page.getByText("System", { exact: true }).click();
  await expect(root).toHaveClass(/dark/);
  await expect(page.getByRole("radio", { name: "System" })).toBeChecked();
  expect(await storedTheme()).toBeNull();

  await testInfo.attach(`standings-dark-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });

  // The Elo table is wider than a phone. At 360px its pinned rank and team columns must stay
  // opaque over the scrolled values in both themes, so check them once at the narrow viewport.
  if (testInfo.project.name === "mobile-360") {
    await page.getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\/history$/);
    await expect(page.getByRole("heading", { name: "Current scores" })).toBeVisible();

    await expectEloPinnedTableOpaque(page, "dark");
    await expectPageDoesNotScrollSideways(page);

    await page.getByText("Light", { exact: true }).click();
    await expect(root).not.toHaveClass(/dark/);
    await expectEloPinnedTableOpaque(page, "light");
    await expectPageDoesNotScrollSideways(page);

    await page.getByText("System", { exact: true }).click();
    await expect(root).toHaveClass(/dark/);
    expect(await storedTheme()).toBeNull();
  }
});

/**
 * Load the page with the application bundle held at the network layer. The inline script in
 * `index.html` must resolve and paint the dark theme before any React code runs, so the first
 * styled paint cannot flash light.
 */
test("applies the dark theme before the application bundle runs", async ({ page }) => {
  let releaseBundle: () => void = () => undefined;
  const bundleGate = new Promise<void>((resolve) => {
    releaseBundle = resolve;
  });
  let markBundleRequested: () => void = () => undefined;
  const bundleRequested = new Promise<void>((resolve) => {
    markBundleRequested = resolve;
  });
  await page.route(/\/(assets\/.*\.js|src\/main\.tsx)$/, async (route) => {
    markBundleRequested();
    await bundleGate;
    await route.continue();
  });

  try {
    await page.goto("/login", { waitUntil: "commit" });
    // The application bundle has been requested but is held here, so nothing from React can run.
    await bundleRequested;
    await page.waitForFunction(() => document.body !== null);

    await expect(page.locator("html")).toHaveClass(/dark/);
    expect(
      await page.evaluate(() => document.documentElement.dataset.theme),
      "the inline script sets the data-theme hook that applyResolvedTheme also writes",
    ).toBe("dark");
    expect(
      await page.evaluate(() => document.documentElement.style.colorScheme),
      "the inline script sets the dark colour scheme",
    ).toBe("dark");

    await page.waitForFunction(
      () => getComputedStyle(document.body).backgroundColor === "rgb(9, 14, 26)",
    );
    expect(
      await page.evaluate(() => document.getElementById("root")?.childElementCount ?? -1),
      "React must not have mounted before the dark first paint",
    ).toBe(0);
  } finally {
    releaseBundle();
  }

  await page.waitForLoadState("load");
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
});
