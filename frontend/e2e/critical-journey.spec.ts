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
  await expect(row.getByRole("img", { name: new RegExp(`^${expected.clinch} — `) })).toBeVisible();
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

/** Header text without the aria-hidden sort arrow, lower-cased for stable comparisons. */
function headerText(text: string): string {
  return text.replace(/[↕▲▼]/g, "").trim().toLowerCase();
}

interface PinnedGeometry {
  rankRight: number;
  teamLeft: number;
  gap: number;
  insidePinned: boolean;
  position: string;
  opaque: boolean;
  borderCollapse: string;
}

/**
 * Scroll a pinned table to its far end and prove that the pinned cell paints above the content
 * that slides underneath it. `pinned` is "two" for a rank + team pair and "one" for a team/season
 * column pinned at the left edge.
 */
async function expectPinnedColumns(
  region: Locator,
  pinned: "two" | "one",
): Promise<PinnedGeometry> {
  const geometry = await region.evaluate((element, mode): PinnedGeometry => {
    element.scrollLeft = element.scrollWidth;
    const table = element.querySelector("table");
    const row = element.querySelector("tbody tr");
    if (table === null || row === null) {
      throw new Error("pinned table geometry unavailable");
    }
    const cells = Array.from(row.children);
    const first = cells[0] as HTMLElement | undefined;
    const second = cells[1] as HTMLElement | undefined;
    const teamCell = mode === "two" ? second : first;
    const rankCell = first;
    if (teamCell === undefined || rankCell === undefined) {
      throw new Error("pinned table cells unavailable");
    }
    // The row may be above or below the current viewport on long pages; a hit test needs it visible.
    teamCell.scrollIntoView({ block: "center", inline: "nearest" });
    element.scrollLeft = element.scrollWidth;
    const teamRect = teamCell.getBoundingClientRect();
    const rankRect = rankCell.getBoundingClientRect();
    const hit = document.elementFromPoint(
      teamRect.left + Math.min(16, teamRect.width / 2),
      teamRect.top + teamRect.height / 2,
    );
    const background = getComputedStyle(teamCell).backgroundColor;
    return {
      rankRight: rankRect.right,
      teamLeft: teamRect.left,
      gap: mode === "two" ? teamRect.left - rankRect.right : 0,
      insidePinned: hit !== null && teamCell.contains(hit),
      position: getComputedStyle(teamCell).position,
      opaque: background !== "rgba(0, 0, 0, 0)" && background !== "transparent",
      borderCollapse: getComputedStyle(table).borderCollapse,
    };
  }, pinned);

  expect(geometry.position, "the pinned cell uses sticky positioning").toBe("sticky");
  expect(geometry.opaque, "the pinned cell has an opaque background").toBe(true);
  expect(geometry.gap, "the rank width matches the team's sticky offset").toBeLessThanOrEqual(1);
  expect(geometry.insidePinned, "no scrolled cell paints above the pinned cell").toBe(true);
  expect(geometry.borderCollapse).toBe("separate");
  return geometry;
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
  const headers = (await overall.getByRole("columnheader").allInnerTexts()).map(headerText);
  expect(headers).toEqual(["#", "team", "owner", "season vp", "w-l", "points for", "w1", "w2"]);
  await expect(page.getByText(/Table scrolls sideways/)).toHaveCount(0);

  const overallRows = overall.getByRole("row");
  await expect(overallRows).toHaveCount(fixture.expected.overall.length + 1);
  for (const [index, expected] of fixture.expected.overall.entries()) {
    await expectOverallRow(overallRows.nth(index + 1), expected);
  }
  await expect(page.getByRole("list", { name: "Playoff designation legend" })).toContainText(
    "X — clinched playoff berth",
  );

  // AC-FE-01: numeric columns sort on the client, keeping the API rank value intact.
  const seasonVpHeader = overall.getByRole("columnheader", { name: "Season VP" });
  const sortBySeasonVp = overall.getByRole("button", { name: "Sort by Season VP" });
  await sortBySeasonVp.click();
  await expect(seasonVpHeader).toHaveAttribute("aria-sort", "descending");
  await sortBySeasonVp.focus();
  await page.keyboard.press("Enter");
  await expect(seasonVpHeader).toHaveAttribute("aria-sort", "ascending");
  const lowestVpRow = overall.getByRole("row").nth(1);
  await expect(rowCells(lowestVpRow).nth(0)).toHaveText("4");
  await expect(lowestVpRow.getByRole("button")).toHaveAccessibleName("Charlie");
  await expect(overall.getByRole("columnheader", { name: "Owner" })).not.toHaveAttribute(
    "aria-sort",
  );

  // AC-FE-02: one table per division, each row showing the team's overall league rank.
  for (const division of fixture.expected.divisions) {
    await expect(page.getByRole("heading", { level: 3, name: division.name })).toBeVisible();
    const table = page.getByRole("region", {
      name: `${division.name} division standings, scrollable horizontally`,
    });
    await expect(table).toBeVisible();
    const divisionHeaders = (await table.getByRole("columnheader").allInnerTexts()).map(headerText);
    expect(divisionHeaders).toEqual(["#", "team", "owner", "season vp", "w-l", "points for"]);
    await expectPinnedColumns(table, "two");
    const rows = table.getByRole("row");
    await expect(rows).toHaveCount(division.teams.length + 1);
    for (const [index, expected] of division.teams.entries()) {
      const row = rows.nth(index + 1);
      await expect(rowCells(row).nth(0)).toHaveText(String(expected.rank));
      await expect(row.getByRole("button")).toHaveAccessibleName(expected.team);
      await expect(
        row.getByRole("img", { name: new RegExp(`^${expected.clinch} — `) }),
      ).toBeVisible();
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
  await expect(page.getByText(/Table scrolls sideways/)).toHaveCount(0);
  await expectPinnedColumns(wapdate, "one");

  // WAPDate VP, wins, and points for sort on the client; the team column is not sortable.
  const wapdateVpHeader = wapdate.getByRole("columnheader", { name: "VP" });
  await wapdate.getByRole("button", { name: "Sort by VP" }).click();
  await expect(wapdateVpHeader).toHaveAttribute("aria-sort", "ascending");
  await wapdate.getByRole("button", { name: "Sort by VP" }).click();
  await expect(wapdateVpHeader).toHaveAttribute("aria-sort", "descending");
  await expect(wapdate.getByRole("row").nth(1)).toContainText("Alpha");
  await expect(wapdate.getByRole("columnheader", { name: "Team" })).not.toHaveAttribute(
    "aria-sort",
  );

  // AC-PO-11/19: the playoff-odds section sits below the overall table, loads independently, and
  // owns the simulation controls (moved off the admin page).
  await expect(page.getByRole("heading", { level: 2, name: "Playoff odds" })).toBeVisible();
  const odds = page.getByRole("region", {
    name: "Playoff odds, scrollable horizontally",
  });
  await expect(odds).toBeVisible();
  await expect(page.getByLabel("Simulations", { exact: true })).toHaveValue("10000");
  await expect(page.getByLabel("Team strength weight", { exact: true })).toHaveValue("1");
  await expect(page.getByLabel("Seed (optional)", { exact: true })).toHaveValue("");
  await expect(page.getByText(/Use 1 to 10,000 simulations/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeVisible();
  await expect(page.getByText(/Regular season complete · projected bracket/i)).toBeVisible();
  await expect(odds.getByRole("columnheader", { name: "Playoff %" })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  await expect(odds.getByRole("columnheader", { name: "Championship %" })).toBeVisible();
  await expect(odds.getByRole("row")).toHaveCount(fixture.teams.length + 1);
  await expect(odds.getByText("100%", { exact: true }).first()).toBeVisible();
  await expectPinnedColumns(odds, "one");

  // The strength weight accepts a numeric string without a leading zero and reruns in place.
  await page.getByLabel("Team strength weight", { exact: true }).fill(".25");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(odds).toBeVisible();
  await expect(odds.getByRole("columnheader", { name: "Championship %" })).toBeVisible();

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
  await expectPinnedColumns(overall, "two");
  await testInfo.attach(`standings-scrolled-${testInfo.project.name}`, {
    body: await overall.screenshot(),
    contentType: "image/png",
  });
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
  const oddsWidth = await odds.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  if (testInfo.project.name === "mobile-360") {
    expect(oddsWidth.scrollWidth).toBeGreaterThan(oddsWidth.clientWidth);
  }
  const oddsTeamHeader = odds.getByRole("columnheader", { name: "Team" });
  expect(await oddsTeamHeader.evaluate((element) => getComputedStyle(element).position)).toBe(
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

  // AC-FE-11/13/16: the Admin nav item is for admins and opens the league admin page. The shell's
  // season picker and header refresh control are gone; the seasons table owns refresh.
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page).toHaveURL(/\/leagues\/\d+\/admin$/);
  await expect(page.getByRole("heading", { level: 1, name: "League admin" })).toBeVisible();
  await expect(page.getByLabel("Season", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("League", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toHaveCount(0);

  // AC-AU-19: every member is listed by email.
  await expect(
    page.getByRole("row", { name: new RegExp(fixture.users.admin.email) }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Members" })).toBeVisible();

  // AC-PO-19: simulation controls live on the standings page, not the admin page.
  await expect(
    page.getByRole("heading", { level: 2, name: "Playoff odds simulation" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Simulations", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Team strength weight", { exact: true })).toHaveCount(0);

  // AC-Elo-*: the admin page hosts the per-league Elo settings with keyboard tooltips.
  await expect(page.getByRole("heading", { level: 2, name: "Elo settings" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Starting rating", exact: true })).toHaveValue(
    "1500",
  );
  await expect(page.getByRole("textbox", { name: "K factor", exact: true })).toHaveValue("24");
  const kTooltip = page.locator("#elo-tip-k_factor");
  await page.getByRole("button", { name: "About the K factor" }).focus();
  await expect(kTooltip).toBeVisible();
  await expect(kTooltip).toContainText("base number of rating points");
  await expect(page.getByRole("button", { name: "Recalculate Elo history" })).toBeVisible();

  // AC-FE-16: one seasons table with the season's cup week, last refresh, and row actions.
  await expect(page.getByRole("heading", { level: 2, name: "Seasons" })).toBeVisible();
  const season = fixture.league.season;
  const seasonsRegion = page.getByRole("region", {
    name: "Seasons, scrollable horizontally",
  });
  await expect(seasonsRegion).toBeVisible();
  await expectPinnedColumns(seasonsRegion, "one");
  const seasonHeader = seasonsRegion.getByRole("columnheader", { name: "Season" });
  await seasonsRegion.getByRole("button", { name: "Sort by Season" }).click();
  await expect(seasonHeader).toHaveAttribute("aria-sort", "ascending");
  await seasonsRegion.getByRole("button", { name: "Sort by Season" }).click();
  await expect(seasonHeader).toHaveAttribute("aria-sort", "descending");
  const seasonRow = page.getByRole("row", { name: new RegExp(`^${season}`) });
  await expect(seasonRow).toBeVisible();
  const select = page.getByLabel(`Cup week for ${season}`);
  await expect(select).toBeVisible();
  await expect(select.locator("option")).toHaveText([
    "No cup week",
    ...Array.from(
      { length: fixture.league.regularSeasonLength },
      (_, index) => `Week ${index + 1}`,
    ),
  ]);
  await expect(seasonRow.getByText("Never")).toHaveCount(0);
  await expect(page.getByRole("button", { name: `Refresh season ${season}` })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add a season" })).toBeVisible();

  // The delete action is confirmed and names the season; cancelling changes nothing.
  await page.getByRole("button", { name: `Delete season ${season}` }).click();
  const deleteDialog = page.getByRole("dialog", { name: `Delete season ${season}?` });
  await expect(deleteDialog).toBeVisible();
  await expect(deleteDialog).toContainText(`only the ${season} season`);
  await deleteDialog.getByRole("button", { name: "Cancel" }).click();
  await expect(deleteDialog).toHaveCount(0);
  await expect(seasonRow).toBeVisible();

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

test("opens the History tab, switches modes and seasons, and passes axe", async ({
  page,
}, testInfo) => {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(fixture.users.admin.email);
  await page.getByLabel("Password", { exact: true }).fill(fixture.users.admin.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/$/);

  // AC-Elo-*: History is a primary, member-visible tab next to Standings and Owner.
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/leagues\/\d+\/history$/);
  await expect(page.getByRole("heading", { level: 1, name: /— history$/ })).toBeVisible();
  await expect(page.getByLabel("Season", { exact: true })).toHaveCount(0);

  const chart = page.getByRole("img", { name: /Elo score history, Round robin/i });
  await expect(chart).toBeVisible();
  await expect(page.getByRole("button", { name: "Round robin" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  const scores = page.getByRole("region", {
    name: "Elo score history current scores, scrollable horizontally",
  });
  await expect(scores).toBeVisible();
  await expect(scores.getByRole("columnheader", { name: "Elo score" })).toBeVisible();
  await expect(scores.getByRole("columnheader", { name: "Last week" })).toBeVisible();
  await expect(scores.getByRole("columnheader", { name: "This season" })).toBeVisible();
  await expect(scores.getByRole("columnheader", { name: "Peak" })).toBeVisible();
  await expect(scores.getByRole("columnheader", { name: "Low" })).toBeVisible();

  // AC-Elo-*: switching the model refetches and changes the accessible chart summary.
  await page.getByRole("button", { name: "Actual schedule" }).click();
  await expect(
    page.getByRole("img", { name: /Elo score history, Actual schedule/i }),
  ).toBeVisible();

  // The time window defaults to All history and can be narrowed to week granularity.
  await expect(page.getByRole("button", { name: "All history" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const fromWeek = page.getByLabel("From week");
  const toWeek = page.getByLabel("To week");
  await fromWeek.selectOption({ label: `${fixture.league.season} W2` });
  await expect(fromWeek).toHaveValue(`${fixture.league.season}-2`);
  await expect(toWeek).toHaveValue(`${fixture.league.season}-2`);
  await expect(
    page.getByRole("img", { name: /Elo score history, Actual schedule/i }),
  ).toHaveAttribute("aria-label", /1 chart weeks from 2026 week 2 to 2026 week 2/);
  await page.getByRole("button", { name: "Current season" }).click();
  await expect(page.getByRole("button", { name: "Current season" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(fromWeek).toHaveValue(`${fixture.league.season}-1`);

  // Double-clicking a legend chip isolates that franchise; the other chips report hidden.
  const bravoToggle = page.getByRole("button", { name: "Show or hide Bravo series" });
  await bravoToggle.dblclick();
  await expect(bravoToggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Show or hide Alpha series" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  // The data-table alternative exposes the exact values and cup markers.
  await page.getByText("View chart data as a table").click();
  const data = page.getByRole("region", { name: "Elo score history data table" });
  await expect(data).toBeVisible();
  await expect(data.getByRole("columnheader", { name: "Team" })).toBeVisible();

  // AC-FE-05 equivalent for the new page: no page sideways scroll, table scrolls inside itself,
  // and the team column stays pinned at every width.
  await expectPageDoesNotScrollSideways(page);
  const scoresWidth = await scores.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  if (testInfo.project.name === "mobile-360") {
    expect(scoresWidth.scrollWidth).toBeGreaterThan(scoresWidth.clientWidth);
  }
  const teamHeader = scores.getByRole("columnheader", { name: "Team" });
  expect(await teamHeader.evaluate((element) => getComputedStyle(element).position)).toBe("sticky");
  await expectPinnedColumns(scores, "two");

  await expectNoBlockingAxeViolations(page, "history");

  await testInfo.attach(`history-${testInfo.project.name}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
});
