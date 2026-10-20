import { expect, test, type Locator, type Page } from "@playwright/test";

import fixture from "../../e2e/fixture.json" with { type: "json" };
import { expectNoBlockingAxeViolations } from "./axe";

const weeks = Object.keys(fixture.weeks)
  .map(Number)
  .sort((left, right) => left - right);

type ExpectedRow = (typeof fixture.expected.overall)[number];

function rowCells(row: Locator): Locator {
  return row.locator("th, td");
}

async function expectOverallRow(row: Locator, expected: ExpectedRow): Promise<void> {
  const cells = rowCells(row);
  await expect(cells.nth(0)).toHaveText(String(expected.rank));
  await expect(row.getByRole("button")).toHaveAccessibleName(expected.team);
  await expect(cells.nth(2)).toHaveText(expected.owner);
  await expect(cells.nth(3)).toHaveText(expected.victoryPoints);
  await expect(cells.nth(4)).toHaveText(`${expected.wins}-${expected.losses}`);
  await expect(cells.nth(5)).toHaveText(expected.pointsFor);
  for (const [index, value] of expected.weeklyVp.entries()) {
    await expect(cells.nth(6 + index)).toHaveText(value);
  }
}

async function expectPageDoesNotScrollSideways(page: Page): Promise<void> {
  const width = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(width.scrollWidth, "the page body must not scroll horizontally").toBeLessThanOrEqual(
    width.clientWidth,
  );
}

test("sign up, join, set owner, and read the seeded standings", async ({ page }, testInfo) => {
  const email = `e2e-member-${testInfo.project.name}-${Date.now()}@example.com`;

  // AC-FE-08: an unauthenticated visit is redirected, and login/signup returns there afterwards.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  await expectNoBlockingAxeViolations(page, "login");

  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(fixture.users.memberPassword);
  await page.getByLabel("Invite code", { exact: true }).fill(fixture.inviteCodes.member);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("main").getByText("No leagues yet", { exact: true })).toBeVisible();

  // Join the stored league by its external id, then select it through the normal league list.
  await page.getByRole("button", { name: "Add league" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("ESPN league id").fill(fixture.league.externalId);
  await page.getByRole("button", { name: "Join league" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(fixture.league.name) }),
  ).toBeVisible();

  // Set the caller's own owner association and return to the standings.
  await page.getByRole("link", { name: "Owner" }).click();
  await expect(page).toHaveURL(/\/leagues\/\d+\/owner$/);
  await page.getByLabel("Owner", { exact: true }).selectOption({ label: fixture.teams[0].owner });
  await page.getByRole("button", { name: "Save owner" }).click();
  await expect(page.getByRole("status")).toHaveText("Owner saved.");
  await page.getByRole("link", { name: "Back to standings" }).click();
  await expect(page).toHaveURL(/\/$/);

  // AC-FE-01: overall standings with rank, team, owner, season VP, record, points for, weekly VP.
  const overall = page.getByRole("region", {
    name: "Overall standings, scrollable horizontally",
  });
  await expect(overall).toBeVisible();
  const headers = (await overall.getByRole("columnheader").allInnerTexts()).map((header) =>
    header.trim().toLowerCase(),
  );
  expect(headers).toEqual(["#", "team", "owner", "season vp", "w-l", "points for", "w1", "w2"]);

  const overallRows = overall.getByRole("row");
  await expect(overallRows).toHaveCount(fixture.expected.overall.length + 1);
  for (const [index, expected] of fixture.expected.overall.entries()) {
    await expectOverallRow(overallRows.nth(index + 1), expected);
  }

  // AC-FE-02: one table per division, each row showing the team's overall league rank.
  for (const division of fixture.expected.divisions) {
    await expect(page.getByRole("heading", { level: 3, name: division.name })).toBeVisible();
    const table = page.getByRole("region", {
      name: `${division.name} division standings, scrollable horizontally`,
    });
    await expect(table).toBeVisible();
    const rows = table.getByRole("row");
    await expect(rows).toHaveCount(division.teams.length + 1);
    for (const [index, expected] of division.teams.entries()) {
      const row = rows.nth(index + 1);
      await expect(rowCells(row).nth(0)).toHaveText(String(expected.rank));
      await expect(row.getByRole("button")).toHaveAccessibleName(expected.team);
    }
  }

  // AC-FE-03: the chart's accessible summary and its data table carry the seeded cumulative VP.
  const ranked = fixture.expected.history
    .slice()
    .sort(
      (left, right) =>
        Number(right.cumulative[right.cumulative.length - 1]) -
        Number(left.cumulative[left.cumulative.length - 1]),
    );
  const summary =
    `Line chart of cumulative victory points, weeks ${weeks[0]} to ${weeks[weeks.length - 1]}. ` +
    ranked.map((team) => `${team.team} ${team.cumulative[team.cumulative.length - 1]}`).join(", ");
  await expect(page.getByRole("img", { name: summary, exact: true })).toBeVisible();

  await page.getByText("View chart data as a table").click();
  const chartData = page.getByRole("region", { name: "Cumulative VP data table" });
  await expect(chartData).toBeVisible();
  for (const expected of fixture.expected.history) {
    const row = chartData.getByRole("row").filter({ hasText: expected.team });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole("rowheader")).toHaveText(expected.team);
    await expect(row.getByRole("cell")).toHaveCount(expected.cumulative.length);
    for (const [index, value] of expected.cumulative.entries()) {
      await expect(row.getByRole("cell").nth(index)).toHaveText(value);
    }
  }

  // AC-FE-05: no page-body sideways scroll at 360/768/1280, wide tables scroll inside their own
  // region, and the team column is pinned at every width.
  await expectPageDoesNotScrollSideways(page);
  const tableWidth = await overall.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  if (testInfo.project.name === "mobile-360") {
    expect(tableWidth.scrollWidth).toBeGreaterThan(tableWidth.clientWidth);
  }
  const teamHeader = overall.getByRole("columnheader", { name: "Team" });
  expect(await teamHeader.evaluate((element) => getComputedStyle(element).position)).toBe("sticky");

  // AC-FE-07: axe on the standings page, after all data views have rendered.
  await expectNoBlockingAxeViolations(page, "standings");

  await testInfo.attach(`standings-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
