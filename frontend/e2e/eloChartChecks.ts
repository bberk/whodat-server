import { expect, type Locator, type Page, type TestInfo } from "@playwright/test";

/**
 * Shared Playwright checks for the Elo history chart.
 *
 * The chart must stay readable at every supported width and in both themes: plain dots instead of
 * marker shapes, no cup markers or end-of-line labels, integer value ticks, a small
 * non-overlapping set of week ticks, and legend chips that neither overlap nor clip. Callers reuse
 * their existing signed-in session so the auth rate limiter is not exercised again.
 */

export interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
  label: string;
}

export async function readBoxes(locator: Locator): Promise<Box[]> {
  return locator.evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        label: element.textContent?.trim() ?? "",
      };
    }),
  );
}

export async function expectNoOverlaps(locator: Locator, description: string): Promise<Box[]> {
  const boxes = await readBoxes(locator);
  expect(boxes.length, `${description} must render`).toBeGreaterThan(0);
  for (let first = 0; first < boxes.length; first += 1) {
    for (let second = first + 1; second < boxes.length; second += 1) {
      const horizontal =
        Math.min(boxes[first].right, boxes[second].right) -
        Math.max(boxes[first].left, boxes[second].left);
      const vertical =
        Math.min(boxes[first].bottom, boxes[second].bottom) -
        Math.max(boxes[first].top, boxes[second].top);
      expect(
        horizontal > 0 && vertical > 0,
        `${description} "${boxes[first].label}" and "${boxes[second].label}" must not overlap`,
      ).toBe(false);
    }
  }
  return boxes;
}

export async function expectPageDoesNotScrollSideways(page: Page): Promise<void> {
  const width = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(width.scrollWidth, "the page body must not scroll horizontally").toBeLessThanOrEqual(
    width.clientWidth,
  );
}

export async function expectReadableChart(
  page: Page,
  theme: "light" | "dark",
  testInfo: TestInfo,
  teamNames: readonly string[],
  variant = "",
): Promise<void> {
  const chart = page.getByRole("img", { name: /Elo score history/i });
  await expect(chart).toBeVisible();

  const chartData = await chart.evaluate((element) => ({
    ariaLabel: element.getAttribute("aria-label") ?? "",
    dots: element.querySelectorAll("circle[data-dot]").length,
    cups: element.querySelectorAll("[data-cup-week]").length,
    markerPaths: element.querySelectorAll("path").length,
    values: Array.from(
      element.querySelectorAll('text[data-axis="value"]'),
      (label) => label.textContent ?? "",
    ),
    labels: Array.from(element.querySelectorAll("text"), (label) => label.textContent ?? ""),
  }));

  expect(chartData.dots, "each series point must be a plain dot").toBeGreaterThan(0);
  expect(chartData.cups, "cup weeks must not get a chart marker").toBe(0);
  expect(chartData.markerPaths, "marker shapes are gone; dots are circles").toBe(0);
  expect(chartData.ariaLabel).not.toMatch(/cup/i);

  // Team names belong to the legend, not to labels at the end of each line.
  for (const name of teamNames) {
    expect(chartData.labels.join(" "), `the chart must not end-label ${name}`).not.toContain(name);
  }

  expect(chartData.values.length, "the value axis must render ticks").toBeGreaterThan(1);
  for (const value of chartData.values) {
    expect(value, `value tick "${value}" must be a whole number`).toMatch(/^-?\d+$/);
  }

  const weekTicks = chart.locator('text[data-axis="week"]');
  expect(await weekTicks.count()).toBeLessThanOrEqual(8);
  await expectNoOverlaps(weekTicks, `${theme} week ticks`);
  await expectNoOverlaps(chart.locator('text[data-axis="season"]'), `${theme} season labels`);

  const wrapperText = (await page.locator('[data-chart="elo"]').textContent()) ?? "";
  expect(wrapperText).not.toMatch(/\bCup\b/);

  const chips = page.locator("[data-series-chip]");
  await expect(chips).toHaveCount(teamNames.length);
  const chipBoxes = await expectNoOverlaps(chips, `${theme} legend chips`);
  const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth);
  for (const box of chipBoxes) {
    expect(box.left, `${box.label} must stay inside the left edge`).toBeGreaterThanOrEqual(-1);
    expect(box.right, `${box.label} must stay inside the right edge`).toBeLessThanOrEqual(
      viewportWidth + 1,
    );
  }
  const overflows = await chips.evaluateAll((elements) =>
    elements.map((element) => ({
      label: element.textContent?.trim() ?? "",
      overflow: element.scrollWidth - element.clientWidth,
    })),
  );
  for (const chip of overflows) {
    expect(chip.overflow, `${chip.label} must not clip or overflow`).toBeLessThanOrEqual(1);
  }

  await expectPageDoesNotScrollSideways(page);
  await testInfo.attach(
    `elo-chart-${variant === "" ? "" : `${variant}-`}${theme}-${testInfo.project.name}`,
    {
      body: await page.locator('[data-chart="elo"]').screenshot(),
      contentType: "image/png",
    },
  );
}

export const DENSE_SEASONS = Array.from({ length: 12 }, (_, index) => 2015 + index);
export const DENSE_WEEKS_PER_SEASON = 14;
export const DENSE_TEAM_NAMES = [
  "Daniel Tiger's Team of Sprouts",
  "Jih*ad London",
  "Conceptions of CTE",
  "KUPP MY LIFE INTO PIECES",
  "CokerHeads in the Naberhood",
  "Night Night",
  "The Mendoza Line",
  "Two-Time Cam Ward Trader",
  "Trust The Process",
  "Unoaked Charbonnet",
  "Alpha",
  "Bravo",
] as const;

/** A twelve-season response shaped like the production payload, with cup weeks and long names. */
export function denseHistory() {
  const weeks: {
    index: number;
    season: number;
    week: number;
    is_cup_week: boolean;
    is_season_start: boolean;
    rated: boolean;
  }[] = [];
  for (const season of DENSE_SEASONS) {
    for (let week = 1; week <= DENSE_WEEKS_PER_SEASON; week += 1) {
      weeks.push({
        index: weeks.length,
        season,
        week,
        is_cup_week: week === 13,
        is_season_start: week === 1,
        rated: week !== 13,
      });
    }
  }

  const teams = DENSE_TEAM_NAMES.map((name, teamIndex) => {
    const series = weeks.map((_, index) =>
      (1500 + Math.sin((index + teamIndex * 3) / 9) * 80 + teamIndex * 4).toFixed(2),
    );
    const values = series.map(Number);
    return {
      team_key: `dense:${teamIndex + 1}`,
      team_id: teamIndex + 1,
      name,
      owner_name: null,
      aliases: [],
      first_season: DENSE_SEASONS[0],
      last_season: DENSE_SEASONS[DENSE_SEASONS.length - 1],
      series,
      seasons: [],
      current: series[series.length - 1],
      last_change: "0.00",
      season_change: "0.00",
      peak: Math.max(...values).toFixed(2),
      peak_at: { season: DENSE_SEASONS[0], week: 1 },
      low: Math.min(...values).toFixed(2),
      low_at: { season: DENSE_SEASONS[0], week: 1 },
      rated_weeks: weeks.filter((week) => week.rated).length,
    };
  });

  return {
    league_id: 1,
    mode: "round_robin",
    seasons: DENSE_SEASONS,
    config: {
      starting_rating: "1500",
      k_factor: "24",
      margin_weight: "0.25",
      margin_cap: "50",
      season_regression: "0.333333",
    },
    weeks,
    season_boundaries: DENSE_SEASONS.slice(1).map((season, index) => ({
      season,
      week_index: (index + 1) * DENSE_WEEKS_PER_SEASON,
    })),
    teams,
    unrated_teams: [],
    warnings: [],
  };
}

/** Route the Elo history request to the dense fixture and reload the history page. */
export async function showDenseHistory(page: Page): Promise<void> {
  const payload = denseHistory();
  await page.route("**/api/v1/leagues/*/elo-history*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    }),
  );
  await page.reload();
  await expect(page.getByRole("img", { name: /Elo score history/i })).toBeVisible();
}

export async function expectDenseSeasonLabels(page: Page, testInfo: TestInfo): Promise<void> {
  const seasons = page
    .getByRole("img", { name: /Elo score history/i })
    .locator('text[data-axis="season"]');
  const count = await seasons.count();
  if (testInfo.project.name === "mobile-360") {
    expect(count).toBeLessThanOrEqual(6);
  } else {
    expect(count).toBe(DENSE_SEASONS.length);
  }
  await expect(seasons.first()).toHaveText(String(DENSE_SEASONS[0]));
}
