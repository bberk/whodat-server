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

test("sign up with a member invite, set owner, and read the seeded standings", async ({
  page,
}, testInfo) => {
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
  // AC-AU-15: the member invite already grants the fixture league, so the member lands on it
  // without the create-or-join step.
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

  // AC-WD-08: the WAPDate section sits below the chart, defaults to the current period, and
  // shows the selected period's rows lowest first.
  await expect(page.getByRole("heading", { level: 2, name: "WAPDate standings" })).toBeVisible();
  const wapdate = page.getByRole("region", {
    name: "WAPDate standings, scrollable horizontally",
  });
  await expect(wapdate).toBeVisible();
  await expect(page.getByRole("radio", { name: /weeks 1-4 · in progress/i })).toBeChecked();
  const wapdatePeriod = fixture.expected.wapdate.periods[0];
  const wapdateRows = wapdate.getByRole("row");
  await expect(wapdateRows).toHaveCount(wapdatePeriod.rows.length + 1);
  for (const [index, expected] of wapdatePeriod.rows.entries()) {
    const row = wapdateRows.nth(index + 1);
    await expect(rowCells(row).nth(0)).toHaveText(expected.team);
    await expect(rowCells(row).nth(1)).toHaveText(expected.victoryPoints);
    await expect(rowCells(row).nth(2)).toHaveText(String(expected.wins));
    await expect(rowCells(row).nth(3)).toHaveText(expected.pointsFor);
  }
  await expect(wapdate.getByTitle("cannot finish last")).toHaveCount(0);

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
  const wapdateWidth = await wapdate.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  if (testInfo.project.name === "mobile-360") {
    expect(wapdateWidth.scrollWidth).toBeGreaterThan(wapdateWidth.clientWidth);
  }
  const wapdateTeamHeader = wapdate.getByRole("columnheader", { name: "Team" });
  expect(await wapdateTeamHeader.evaluate((element) => getComputedStyle(element).position)).toBe(
    "sticky",
  );

  // AC-FE-07: axe on the standings page, after all data views have rendered.
  await expectNoBlockingAxeViolations(page, "standings");

  await testInfo.attach(`standings-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});

test("admin reads the league admin page without blocking accessibility issues", async ({
  page,
}, testInfo) => {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(fixture.users.admin.email);
  await page.getByLabel("Password", { exact: true }).fill(fixture.users.admin.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/$/);

  // AC-FE-11/13: the Admin nav item is for admins and opens the league admin page. The shell's
  // season picker is hidden here because the page names the season it administers.
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page).toHaveURL(/\/leagues\/\d+\/admin$/);
  await expect(page.getByRole("heading", { level: 1, name: "League admin" })).toBeVisible();
  await expect(page.getByLabel("Season", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("League", { exact: true })).toBeVisible();

  // AC-AU-19: every member is listed by email.
  await expect(
    page.getByRole("row", { name: new RegExp(fixture.users.admin.email) }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Members" })).toBeVisible();

  const select = page.getByLabel("Cup week for this season");
  await expect(select).toBeVisible();
  await expect(select.locator("option")).toHaveText([
    "No cup week",
    ...Array.from(
      { length: fixture.league.regularSeasonLength },
      (_, index) => `Week ${index + 1}`,
    ),
  ]);

  // AC-AU-21/AC-FE-14: a generated invite shows its raw code once with a one-time warning.
  await page.getByRole("button", { name: "Generate invite" }).click();
  await expect(page.getByLabel("Invite code")).toBeVisible();
  await expect(page.getByText(/shown only once/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy code" })).toBeVisible();

  // AC-AU-22: the destructive action sits apart and needs the league name typed.
  await expect(
    page.getByRole("heading", { level: 2, name: "Danger zone: delete this league" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete league permanently" })).toBeDisabled();

  await expectPageDoesNotScrollSideways(page);
  await expectNoBlockingAxeViolations(page, "league admin");

  await testInfo.attach(`league-admin-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});

test("sign up with an admin invite and get forced through onboarding", async ({
  page,
}, testInfo) => {
  const email = `e2e-admin-${testInfo.project.name}-${Date.now()}@example.com`;
  const addLeagueRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/leagues")) {
      addLeagueRequests.push(request.url());
    }
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByRole("heading", { level: 1, name: "Create an account" })).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(fixture.users.memberPassword);
  await page.getByLabel("Invite code", { exact: true }).fill(fixture.inviteCodes.admin);
  await page.getByRole("button", { name: "Create account" }).click();

  // AC-AU-14: an admin invite carries no league, so the account lands on mandatory onboarding.
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole("heading", { level: 1, name: "Add your ESPN league" })).toBeVisible();
  await expect(page.getByLabel("ESPN league id")).toBeVisible();
  await expect(page.getByLabel("Season")).toHaveValue(String(new Date().getFullYear()));

  // Standings stay unreachable until a league is added.
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.goto("/leagues/1/owner");
  await expect(page).toHaveURL(/\/onboarding$/);

  // Client-side validation stops every incomplete submit before it reaches the API, so the suite
  // never depends on a real ESPN call the e2e backend cannot make.
  await page.getByRole("button", { name: "Add league and continue" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter your ESPN league id.");

  await page.getByLabel("ESPN league id").fill("123456");
  await page.getByLabel("Season").fill("1999");
  await page.getByRole("button", { name: "Add league and continue" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Season must be a whole year between 2000 and 2100.",
  );

  await page.getByLabel("Season").fill(String(new Date().getFullYear()));
  await page.getByRole("button", { name: "Add league and continue" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter both ESPN_S2 and ESPN_SWID.");
  expect(addLeagueRequests).toEqual([]);

  // AC-FE-05 and AC-FE-07: the onboarding page fits the 360px body and has no blocking axe issues.
  await expectPageDoesNotScrollSideways(page);
  await expectNoBlockingAxeViolations(page, "onboarding");

  await testInfo.attach(`onboarding-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
