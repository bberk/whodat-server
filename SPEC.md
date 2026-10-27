# SPEC: Victory Points Fantasy Football Standings

> Status: DRAFT v0.1. Items marked **[DECISION]** are proposed defaults the human owner should confirm or change. Items marked **[OPEN]** are unresolved questions (see the end of this file).

## 1. Purpose

A website that shows fantasy football standings under a custom scoring system called **Victory Points (VP)**. ESPN's built-in standings only rank by win/loss record, so this site pulls league data from ESPN, computes VP, and displays standings and trends.

Members join a league with an invite code, may associate themselves with one of the league's owners, and can view that league's standings.

## 2. Goals

1. Accurately compute VP for every team, every week, per the rules in section 3.
2. Show overall and per-division standings, a per-week VP table, and a cumulative VP chart.
3. Work well on mobile and desktop browsers with a modern look.
4. Isolate ESPN-specific code behind an interface so another provider (Sleeper, Yahoo, manual CSV, etc.) can be added without changing the VP engine, database schema, API, or frontend.

## 3. Victory Points rules (authoritative)

Each regular-season week, every team earns VP from four components:

| Component | VP |
|---|---|
| Head-to-head (H2H) win | +1 |
| Score in the top half of the league that week | +1 |
| Highest score of the week | +1 |
| Lowest score of the week | -1 |

A team's weekly VP is the sum of its components. Season VP is the sum across weeks.

### 3.1 Tie handling (VP is split)

- **H2H tie** (two matched-up teams have identical scores): each team gets 0.5 VP for the H2H component.
- **Tie for highest score**: the 1 VP is split evenly among all tied teams (2 teams → 0.5 each; 3 teams → 1/3 each).
- **Tie for lowest score**: the -1 VP is split evenly among all tied teams (2 teams → -0.5 each).
- **Tie across the top-half cutoff** **[DECISION]**: the top-half VP is a pool of one point for each of the top `floor(N/2)` rank positions (N = number of teams). Teams tied across the cutoff share the points for the rank positions inside the cutoff equally. Example with N=6 (3 slots): scores 130, 120, 100, 100, 80, 70 → the two teams on 100 occupy ranks 3 and 4; only rank 3 is inside the cutoff, so each gets 0.5 top-half VP.

Splitting is exact (fractions such as 1/3 are possible). See ACCEPTANCE.md for worked examples.

### 3.2 Standings ranking

Teams are ranked by, in order:

1. Total season VP (descending)
2. Total H2H wins in the season (descending) **[DECISION]** H2H ties do not count as wins.
3. Total points for in the season (descending)

If all three are equal, teams share the same rank (display order is then alphabetical by team name, but the rank number is shared).

### 3.3 Which weeks count **[DECISION]**

- VP is computed for **completed regular-season weeks only**. Playoff weeks are displayed (if at all) but earn no VP.
- A week is "completed" when ESPN reports the matchup period as finished.
- Bye weeks or teams without an opponent: still earn the top-half / high / low components; no H2H component.

### 3.4 Cup week

A league season may designate **one optional regular-season week** as a cup week. On that week:

- No head-to-head VP is awarded, so the H2H component is 0 for every team regardless of matchup result.
- The high-score, top-half, and worst-score components are awarded exactly as in a normal week.
- Matchup results do not change any team's W-L-T record.
- Points for still count, the week still contributes its VP to the season total, and the weekly and
  cumulative VP series include it.

A season without a designated cup week behaves exactly as an ordinary season. The cup week is a
per-season setting, it is not inferred from provider data, and it must be a week number between 1
and the season's regular-season length. Choosing the cup week is an admin action (section 4.1).

### 3.5 Elo history

Elo is a companion view to Victory Points. It never changes VP, W-L-T, rankings, cup-week
scoring, or playoff rules.

- **Franchise identity.** A rating follows the team slot, keyed by `team.external_id` across
  seasons, not the owner. A rename or owner change keeps the rating; the display uses the latest
  stored name/owner and lists earlier names as aliases. Equal current names are disambiguated in
  the UI, never by using the name as a key.
- **Scope.** Only completed regular-season weeks count. Playoff and incomplete weeks are
  excluded. Byes (a matchup with no away team) move no rating. The cup week is excluded entirely
  in actual-schedule mode and counted in round-robin mode.
- **History is derived.** Ratings are recomputed on every read from stored seasons, teams,
  matchups, and scores; there is no snapshot table. Adding, deleting, or correcting a season is
  reflected on the next read.
- **Formula.** Every franchise starts at the league's configured starting rating (default 1500),
  including a franchise that first appears mid-history. For teams `a` and `b`:

  `E_a = 1 / (1 + 10 ** ((R_b - R_a) / 400))`

  `R_a' = R_a + K_effective * (S_a - E_a)` and `R_b' = R_b - K_effective * (S_a - E_a)`, where
  `S_a` is 1 for a win, 0.5 for a tie, and 0 for a loss. Both teams use the same signed delta, so
  a decisive matchup is exactly zero-sum.
- **Margin bonus.** `K_effective = K * (1 + margin_weight * min(|margin|, margin_cap) /
  margin_cap)`, where margin is the absolute difference in points. Ties have a zero margin and
  use the base K.
- **Season regression.** Before each new stored season, every returning franchise moves toward
  the starting rating: `R' = start + (R - start) * (1 - season_regression)`. A franchise absent
  for one or more stored seasons applies one regression per missed season boundary when it
  returns. The default regression is one third.
- **Modes.** `actual_schedule` updates both teams from each real head-to-head matchup and skips
  cup weeks. `round_robin` counts every completed regular-season week including cup weeks,
  computes every unordered pairing's delta from that week's start-of-week ratings, and applies
  each team's average pairwise delta for the week; update order does not matter.
- **Configuration.** Settings are per league in `elo_config`: starting rating (1000-2000, default
  1500), K factor (1-100, default 24), margin weight (0-1, default 0.25), margin cap (1-200,
  default 50), and season regression (0-1, default 1/3). Missing rows mean the defaults. Only a
  league admin member may change them; only an admin member may read them for the settings form.
- **Display.** The current rating is rounded to the nearest whole number. Weekly and season
  changes display to two decimal places with an explicit sign. Peak and low include the starting
  rating; a peak or low equal to that starting value is labelled "start". "This season" is
  measured from the post-reset baseline before the team's latest season, not the prior season's
  final rating.

### 3.6 Playoff clinch designations

Standings show a per-team playoff designation once a season reaches its final four regular-season
weeks (four or fewer weeks remaining). The calculation is season-specific and uses the playoff
field size stored from the provider's season settings.

- The two division winners are seeds 1-2 and receive first-round byes. The better division winner
  is the **Z** top seed; the other division winner is **Y**. Any other team that has clinched a
  playoff berth is **X**, and a team that cannot mathematically make the playoffs is **E**.
- With no divisions or one division there is no second automatic berth: the overall #1 seed is
  **Z**, other clinched berths are **X**, and **Y** is not used.
- A team has at most one designation. Precedence is **E**, then **Z**, then **Y**, then **X**;
  otherwise the designation is absent.
- The clinch tiebreak is season VP then wins only. Points for is ignored because it could still
  change an apparently decided position. If VP and wins leave a team level with a competitor at a
  decisive boundary, that outcome is undecided and no clinch or elimination is shown for it.
- The remaining regular-season schedule matters. A designation is calculated only from a complete
  stored schedule for every remaining week, including head-to-head pairings and explicit byes.
  Missing metadata or schedule coverage produces no designations rather than a guess; seasons
  stored before this feature need a re-sync.
- Cup weeks still contribute their VP and scoring components, but award no H2H VP or win. The
  calculation therefore treats a cup-week pairing as a bye for win/H2H purposes.
- The search is conservative: it first uses cheap feasible VP/wins bounds and only enumerates
  remaining H2H outcomes for plausible candidates. If a per-team node cap is exceeded, that team
  gets no designation. A withheld badge is preferred to a false one, so a very ambiguous season
  can show fewer designations than a full brute-force result would.

### 3.7 Playoff odds

The standings page also shows an **estimate** of each team's chance of making the playoffs, earning
a first-round bye, winning its division, and winning the championship. Odds are derived by
simulating the remaining regular-season weeks with the full Victory Points system and then
projecting the playoff bracket; they are not a new scoring rule and never change standings, clinch
designations, Elo, or stored data.

- **Simulation.** Each simulated season starts from the exact current totals (season VP, H2H wins,
  and points for) and draws a score for every team in every remaining regular-season week. Weekly VP
  is computed with the same rules as section 3, including H2H ties, the top-half cutoff, high/low
  splits, byes, and cup weeks. A cup week adds VP and points for but no H2H win.
- **Score model.** Team strength is the team's mean points shrunk toward the league mean with three
  pseudo-games. Future scores combine the shrunk team level with an empirical residual drawn from
  the team's own residuals (when it has at least two observations, with four pseudo-games of
  shrinkage toward the pooled set) or the pooled residual set. With fewer than two counted weeks (or
  no team with two observations) the model uses week-centred residuals and no team deviation. No
  prior or invented score is used.
- **Team-strength weight.** The simulation accepts one optional dial, a team-strength weight `w` from
  0 to 10 inclusive with up to 18 decimal places. It scales only the projected future scores:
  `base_t = mu_bar + w * delta_t`, and the probability of drawing a team's own residuals becomes
  `min(1, w) * n_t / (n_t + 4)`. At `w = 1` the regular-season projection is unchanged from the
  previous model and the projected bracket uses its own derived draw stream, so championship
  probabilities are new; at `w = 0` every remaining matchup is
  even because all teams share the grand mean and the pooled residuals, while the exact current VP,
  wins, and points for still decide seeding; values above 1 overweight stronger teams. The weight is
  reported with the result and is part of the cache identity; it is never stored.
- **Seeding.** The final table ranks by season VP, then H2H wins, then points for, then team name and
  id. Division winners are seeded first, in that same order; the remaining teams follow in overall
  order. Exactly `playoff_team_count` teams qualify.
- **Byes.** The bracket's next power of two above the playoff field determines the bye count:
  `max(0, next_power_of_two(P) - P)`, capped at the number of divisions. Byes go only to division
  winners, in seed order. With more divisions than byes, the remaining division winners are seeded
  normally and receive no bye. A field and bye count that cannot form a complete bracket, such as an
  odd number of non-bye teams, is unavailable instead of inventing a bye.
- **Playoff projection.** After each simulated regular season the qualifiers are seeded and a
  single-elimination bracket is played with reseeding after every round: the highest remaining seed
  plays the lowest, byes apply only in the first round, each round draws fresh scores from the same
  team-strength and residual model, the higher score wins, and an exact tie goes to the higher seed.
  The simulation continues until one champion. Real stored playoff matchups are excluded: the
  bracket is a projection, not a replay.
- **Divisions.** At least one stored division is required. Every team must have a non-empty
  division. The simulation does not guess a division or a playoff field.
- **Unavailable.** No completed week, a missing or unusable playoff field, an incomplete or
  inconsistent remaining schedule (including a playoff game inside the regular season), an
  unsupported division shape, and an unformable playoff bracket produce an explicit unavailable
  result. Corrupt season settings still produce the standings-style structured error.
- **Current season only.** Playoff odds describe the season in progress, so they are available only
  for the league's current season: the latest stored season (the maximum stored season for the
  league). A prior stored season is rejected by the API and shows no section, because its schedule
  is finished rather than remaining.
- **Presentation.** Probabilities are estimates with a 95% interval for Monte Carlo uncertainty; the
  interval is not a statement of model certainty. A finished regular season still projects its
  playoff bracket from the final seeds rather than reporting a deterministic champion.

## 4. Functional requirements

### 4.1 Data ingestion

- Fetch league data from ESPN: league metadata, owners, teams (per season, including division), the full regular-season schedule (including future weeks), and weekly scores. The season metadata includes ESPN's playoff field size.
- Sync is **idempotent**: re-running it never creates duplicates and updates any changed values (ESPN scores can be corrected after the fact). After a sync, VP is recomputed for any affected weeks.
- Future regular-season matchups are stored as incomplete and have no team-week scores or VP. Syncing an incomplete week reconciles it against the provider: removed or moved pairings and their stale scores are deleted, current pairings are inserted or updated, home/away swaps and byes are handled, and completed weeks are not reconciled.
- Sync is runnable on demand via a CLI command, and schedulable via cron or equivalent.
- Private ESPN leagues require ESPN auth cookies (`espn_s2`, `SWID`). A league admin supplies them
  when adding the league. Credentials come only from a user's membership, where they are stored
  encrypted at rest, and are decrypted only in the provider layer. They are never committed, never
  logged, and never returned by the API.
- Adding a league validates the credentials by constructing an ESPN league object before anything is
  stored; a failed validation stores nothing.
- A league-wide refresh can be triggered through the API by a member whose membership holds
  credentials; the UI exposes a per-season refresh in the admin seasons table. Refresh is rate
  limited per league and per user; members without credentials cannot refresh.
- Historical seasons can be backfilled by specifying a season.
- Each season optionally stores one **cup week** (section 3.4): the week number, within the season's
  regular-season length, where H2H VP and W/L/T do not apply. `null` means no cup week. Only an
  admin may set or clear it; members may read it. Changing it persists the setting and recomputes
  the league's VP from stored data in the same operation. A sync of a season that already has a cup
  week honours it.

**WAPDate standings.** WAPDate is a view over stored season data, not extra ingestion. The regular
season is split into three fixed, independent periods: weeks 1-4, weeks 5-8 and weeks 9-12. Weeks
13 and later are ignored, and no victory points, wins or points for carry between periods.

A period is offered once at least one of its weeks is completed. It is **complete** when the
highest completed regular-season week is at least its end week; otherwise it is the **current**
period. Each team's period totals are its VP over the period's completed weeks (with cup-week
scoring), its head-to-head wins in the period excluding the cup week, and its points for in the
period including the cup week. The table lists the worst team first: VP ascending, then wins
ascending, then points for ascending, then team name.

For the current period only, a team is greyed as safe from last place when another team can no
longer finish below it on VP and wins. The bound assumes a team can lose -1 VP per remaining week
and another team can gain at most +3 VP per remaining non-cup week (+2 on the cup week, which has
no head-to-head VP), with at most one win per remaining non-cup week. Points for is ignored by the
bound. Completed periods show the actual result with no greying.

The WAPDate section is a **per-league display setting**, not scoring data: it is on by default for
every existing and new league, and a league admin may turn it off. Turning it off hides the section
from the standings page and stops the page requesting its data; WAPDate itself is still derived from
the same stored season data and no VP, wins, points for, or ranking change.

### 4.2 Data storage

Persisted entities (see ARCHITECTURE.md for the schema):

- **League** (and metadata, including provider and external ID)
- **Owner**
- **League season** (per season: provider metadata including regular-season length and playoff field size, optional cup week, last refreshed instant)
- **Team** (per season; includes division and owner)
- **Matchup** (season, week, home team, away team; future incomplete pairings included)
- **Score** (team, season, week, points, victory points and its component breakdown; absent for future unplayed matchups)
- **User** (email, password hash, role)
- **Invite** (league, code hash, role, expiry)
- **Membership** (user, league, optional owner association, encrypted ESPN credentials)
- **Elo config** (one row per league, optional: starting rating, K factor, margin weight, margin
  cap, and season regression; no row means the documented defaults)

The database engine must be swappable between SQLite and Postgres with no application code changes (config only).

### 4.3 Provider abstraction

All ESPN-specific code lives behind a provider interface that returns normalized data, including the season's full regular-season pairing schedule and playoff field size. Adding a new provider must require only: a new adapter module, registration of the provider, and no changes to the VP engine, database schema, API, or frontend.

### 4.4 Accounts and access

- Accounts are invite-only: signing up requires a valid, unexpired shared invite code, which is
  validated against its stored hash. Every invite carries either the **admin** or **member** role.
  **Admin invites** are league-less: they create an account that can then add any league through the
  UI without another invite. **Member invites** are bound to exactly one league and grant that
  membership automatically at signup; a member invite with no league, or an admin invite with a
  league, is rejected at creation. Invites default to a 7-day expiry. The raw code is shown only
  once when an admin creates the invite and is never retrievable afterwards; regenerating means
  creating a new invite.
- Users and leagues are many-to-many. A membership row links a user to a league, optionally records
  that user's owner (team) association, and stores that user's ESPN credentials, encrypted at rest.
- An admin can add a league by providing `espn_league_id`, an optional season, and optional
  ESPN_S2/ESPN_SWID; no invite is required. The backend validates by constructing an ESPN league
  object before storing anything; on success it stores the league, the membership, the encrypted
  credentials, and syncs the requested season.
- An admin who belongs to an existing league can add another season to it. The backend syncs that
  season immediately using the caller's own stored league credentials (the same credential model
  as refresh), with no fallback to another member's credentials or the environment. A caller with
  no stored credentials for that league, a season that already exists, or a provider failure is
  rejected without leaving a partial season behind. A successful add records that season's
  last-refreshed time.
- A user who signs up with an admin invite has no league and must complete a mandatory "create your
  league" step (ESPN league id, season, ESPN_S2, ESPN_SWID) before reaching standings. A user who
  signs up with a member invite already has that league and goes straight in.
- An existing member joins an additional league by redeeming a member invite code in the UI, not by
  supplying a bare league id. Admins may add any league with credentials without an invite.
- Credentials are encrypted at rest with AES-256-GCM under `LEAGUE_CREDENTIALS_KEY`, decrypted only
  in the provider layer, and never logged or returned by the API.
- A member whose membership holds credentials can trigger a league-wide refresh through the API;
  refresh is rate limited per league and per user. Admin per-season refresh uses a separate,
  configurable per-user bucket so refreshing several stored seasons does not consume the
  league-wide quota. Members without credentials cannot refresh.
  The only refresh control in the UI is the admin seasons table, where an admin member refreshes
  one stored season at a time using the same credential and rate-limit rules.
- An admin who belongs to a league can refresh or delete a single stored season from the admin
  seasons table. Refreshing a season syncs only that season through the provider and updates its
  last-refreshed time; it never creates or duplicates a league or season. Deleting a season removes
  only that season's stored data (the `league_season` row, teams, matchups, and scores) while
  keeping the league, owners, memberships, invites, and every other stored season. Both operations
  are atomic.
- Each stored season records the instant of its last successful provider sync as a nullable
  timestamp. Add-season and refresh set it; changing the cup week never does.
- After joining, a user may associate their membership with one of that league's owners.
- An admin who belongs to a league can manage its membership from the league admin page. The page
  lists every account associated with the league by email (the account identifier; there is no
  username) with its role, owner association, and whether it holds stored credentials. An admin can
  remove a member, including themselves or another admin; removal deletes only that user's
  membership in this league (with its owner association and stored credentials) and never the
  account or its other leagues. Removal is refused when it would leave the league with no admin
  member.
- The league admin page can generate either a member invite bound to this league or a league-less
  admin invite. Both default to a seven-day expiry and are bounded. The raw code is returned once
  at creation and is never retrievable afterwards; only its hash is stored.
- An admin who belongs to a league can delete that league from the league admin page after typing
  its name to confirm. Deletion removes the league and its own data only (seasons, teams, owners,
  matchups, scores, memberships, Elo settings, and invites bound to it); user accounts, league-less
  admin invites, and other leagues are untouched.
- Not in v1: email verification, password reset, social login, claiming more than one owner in a
  league.

### 4.5 Frontend

Pages and views:

1. **Sign up (invite code) / Log in**
2. **Standings**
   - Season selector (default: current season).
   - **Overall standings table**: rank, team, owner, season VP, H2H record (W-L-T), points for, and one column per week showing that week's VP. A proven playoff designation appears beside the team: **Z** top seed, **Y** division winner, **X** clinched playoff berth, or **E** eliminated. A text legend near the table explains all four; status is never conveyed by colour alone.
   - **Division standings**: one table per division; the division only filters and groups the rows, and the rank displayed for each team is its overall league rank. Division rows carry the same designation as the overall table.
   - **Playoff odds**: below the WAPDate standings, a separately loaded section estimates each team's
     playoff berth, first-round bye, division title, and championship from a Monte Carlo simulation
     of the remaining season and a projected, reseeded bracket (section 3.7). It shows Team,
     Division, Playoff %, Bye %, and Championship %, with the uncertainty range; numeric columns sort
     on the client, and the team column is pinned at narrow widths. The section owns the simulation
     controls: iteration count (1-10,000 for members, 1-100,000 for admins, default 10,000), a
     team-strength weight (0-10, any castable decimal form, default 1), an optional seed, and a Run
     action. Loading, unavailable, empty, and error states are present, and the copy says these are
     estimates.
   - **WAPDate standings**: below the cumulative VP chart, a toggle for the offered four-week
     periods (weeks 1-4, 5-8, 9-12) labelled with the week range and complete/in-progress state,
     defaulting to the current period or the latest complete one. The selected period lists the
     worst team first with Team, VP, Wins and PF. Teams safe from last place in the current period
     are greyed and carry a text/accessible "Safe" marker, never colour alone. The section renders
     only when the selected league's WAPDate display setting is on (the default); when it is off
     the page shows no heading or section and requests no WAPDate data.
   - Tapping/clicking a team highlights it in the chart.
3. **VP chart**: a line chart of cumulative VP over time, x-axis = week, one line per team. Users can highlight a team and toggle teams on and off. Must be legible on a phone.
4. **History**: a member-visible tab next to Standings and Owner, with its own route
   `/leagues/:leagueId/history`. It shows a running Elo chart from the first stored season and a
   current-ratings table.
   - A mode control switches between **Actual schedule** and **Round robin**, with an accessible
     explanation of the difference; switching refetches.
   - The chart has one line per franchise, season boundary rules and labels, a plain dot at every
     rated week (cup weeks are not marked), legend controls to toggle and select series, a text
     summary, and a data-table alternative. A season filter defaults to **All history**.
   - The current-ratings table shows team, current rating (whole number), change this week and this
     season (two decimals with signs), peak, low, and owner, sorted by current rating. It scrolls
     inside its card with a sticky team column and no page-body sideways scroll at 360px.
   - Loading, empty (no rated weeks), and error states are present; colour is never the only signal.
5. **League admin**: a page available only to signed-in admins for a selected league. Simulation
   adjustment controls live on the standings Playoff odds section, not here. It manages the league's
   membership (member list by email with role, owner association, and credential status, and
   confirmed removal with a last-admin guard and a credential warning), a single **seasons table**
   with one row per stored season (season year, cup-week dropdown, last refreshed time, a per-season
   refresh action, and a confirmed per-season delete action) plus a "+" action that adds a season,
   an **Elo settings** section with the five per-league values and an accessible explanation on
   each field, and a **Recalculate Elo history** action that saves the values and invalidates the
   History view, a **Display settings** section with a per-league WAPDate toggle (on by default)
   that saves immediately and updates the shared league list so the standings view honours it,
   invite generation (a member invite bound to the league or a league-less admin invite, with the raw
   code shown once and a copy control), and a clearly separated destructive action that deletes the
   league after typing its name to confirm. Cup-week changes save immediately for that row and
   recompute standings from stored data without contacting the provider. Every section and every row
   has loading, error, and success states. Non-admins are redirected to the standings and do not see
   the Admin navigation item.

UI requirements:

- Responsive: usable on phones (~360px wide) through desktop.
- The season picker belongs to the standings view. It is not shown on the history, owner, or league
  admin pages; those pages keep the league switcher. There is no refresh control in the shell: the
  admin seasons table is the only refresh mechanism in the UI.
- The standings page keeps its section headings, tables, chart, and the meta line under the page
  title, but shows no instructional subheader paragraph under a section and no footer note.
- Modern, clean visual design; light and dark mode is nice to have, not required.
- Wide tables scroll horizontally inside their own container, with the team column pinned (sticky).
- Accessible: sufficient color contrast, keyboard navigable, chart series distinguishable without relying on color alone (e.g., highlight on select, labels).
- Meaningful loading, empty, and error states.

### 4.6 Development workflow and quality gates

How code gets into `main` is part of the product's requirements, because the code is written by a swarm of agents and the workflow is what keeps quality independent of any single agent.

1. **Pre-commit checks.** Every commit runs `pre-commit` hooks: ruff lint and format and mypy for the backend; eslint, tsc, and prettier for the frontend; secret scanning; basic file hygiene; and a block on committing directly to `main`. Tests run on push. Hooks may not be bypassed (`--no-verify`, `SKIP`), and CI re-runs all hooks on the whole repo.
2. **Branch per task, PR per branch.** Work happens on `agent/<task-id>-<slug>` branches. After each commit by an agent, the branch is pushed to origin and a **draft** pull request is opened if none exists. Draft PRs are not reviewed. The author marks the PR ready when the task meets its definition of done.
3. **Independent review.** A ready PR is reviewed by a different agent that shares no context with the author: a new session, a clean checkout, and reviewer instructions taken from `main` rather than from the PR. The reviewer judges the change against the project docs and the acceptance criteria and posts its verdict (approved or changes requested) and what it verified as a review comment. GitHub does not let an author approve a PR, so the reviewer reports and a **human** makes the formal approval.
4. **Merge.** A human approves and merges every ready PR — rebase by default, or squash — after CI is green and the independent review has run on the current head commit; the branch is then deleted. The ruleset requires linear history, so there are no merge commits. Agents never merge, and never merge their own work. Changes to the rules and gates themselves (the four spec documents, `.github/`, `.opencode/`, `scripts/`, `.pre-commit-config.yaml`) are never auto-merged and always need a human.
5. **Coverage reporting.** CI measures coverage for the backend and the frontend and posts a combined report as a comment on each PR, updated on every push. Thresholds: backend total >= 85% (lines and branches measured), VP engine 100% (lines and branches), frontend thresholds as configured in its test runner **[DECISION]** (proposed starting point: 80% lines and statements).
6. **GitHub setup.** Repo settings (squash and rebase merges, linear history, branch cleanup) and a ruleset on `main` requiring a pull request and passing CI are set up once by the owner. No approval is required, because a human makes every approval and merge and GitHub forbids self-approval; the reviewer agent only reports. No second account or reviewer token is needed. See `docs/GITHUB_SETUP.md`. Server-side enforcement depends on repo visibility and plan (see Q9).

## 5. Non-functional requirements

- **Correctness over cleverness**: the VP engine is pure, deterministic, and exhaustively tested.
- **Numeric safety**: scores are compared as exact decimals, VP is computed with exact fractions; never use binary floating point for score or VP comparison.
- **Security**: passwords hashed with a modern algorithm (argon2id or bcrypt); secrets from environment only; authorization enforced server-side on every league-scoped endpoint; basic rate limiting on auth endpoints.
- **Performance**: standings for a 12-team, 18-week season respond in under 500 ms (p95) on a modest host.
- **Portability**: `docker compose up` (or equivalent documented steps) brings up a working local dev environment.

## 6. Out of scope for v1

Live in-game score updates, playoff VP, trade/transaction tracking, push notifications, league commissioner admin UI, non-ESPN providers (only the interface), payments, public (unauthenticated) league pages.

## 7. Proposed tech stack **[DECISION]**

The owner has no hard requirements and limited frontend experience, so this favors mainstream, well-documented tools that agents write reliably.

- **Backend**: Python 3.15, FastAPI, SQLAlchemy 2.x + Alembic migrations, Pydantic. Python lets the ESPN adapter use the `espn-api` library (cwendt94/espn-api), which the legacy implementation used, directly.
- **Database**: SQLite for local dev and tests; Postgres for CI and production. Same code for both.
- **Frontend**: React + TypeScript + Vite, Tailwind CSS, a component library such as shadcn/ui, Recharts for the chart, TanStack Query for data fetching.
- **API contract**: FastAPI's generated OpenAPI spec; frontend types are generated from it.
- **Tooling**: `uv` (Python), `pnpm` (frontend), `pytest` + `pytest-cov`, `ruff`, `mypy`, `vitest` + coverage, `eslint`, `prettier`, Playwright (a small number of end-to-end tests), `pre-commit`, GitHub Actions for CI, the `gh` CLI for PR automation.

## 8. Suggested milestones

1. **M0 Skeleton**: repo layout, tooling, a passing "hello" test in both backend and frontend, DB migrations running, pre-commit hooks installed and passing, CI green with the coverage comment working, and the GitHub setup from `docs/GITHUB_SETUP.md` done and verified with one trivial end-to-end PR (commit, draft PR, review, merge). Do this before any parallel work starts.
2. **M1 VP engine**: pure module plus the full unit test suite from ACCEPTANCE.md (no I/O).
3. **M2 Data layer + provider interface**: schema, repositories, `LeagueProvider` interface, a fake in-memory provider for tests.
4. **M3 ESPN adapter + sync**: real ESPN adapter, sync CLI, idempotency tests (using recorded fixtures, not live calls).
5. **M4 API + auth**: standings endpoints, invite signup, memberships, league credentials, owner
   association, authorization tests.
6. **M5 Frontend**: login, standings tables, chart, responsive polish (can start on stubbed API data once the API contract exists).
7. **M6 Hardening**: end-to-end tests, docs, Docker Compose, deployment notes.

## 9. Open questions **[OPEN]**

Agents must not guess on these. Record any new ones in `docs/OPEN_QUESTIONS.md`.

1. **Top-half ties across the cutoff**: confirm the proposed splitting rule in 3.1.
2. **Odd number of teams**: is top half `floor(N/2)` (proposed) or something else?
3. **Owner linking** *(resolved)*: a user joins a league with an invite code, then may associate their
   membership with one of that league's owners; the association is optional and limited to the
   caller's own membership.
4. **Account features** *(resolved)*: one user can belong to multiple leagues through memberships.
   Password reset remains out of scope for v1.
5. **Do H2H ties count toward the "wins" tiebreaker?** (Proposed: no.)
6. **Playoff weeks**: confirm no VP is awarded in the playoffs.
7. **Hosting target**: affects scheduling (cron vs in-process scheduler) and the Postgres choice.
8. **Number of leagues and seasons** the site needs to support at launch (assumed: one league, with the option to backfill past seasons).
9. **Repo visibility and GitHub plan** *(resolved)*: **public repo on the Free plan**. GitHub enforces branch rulesets there at no cost, and the pre-commit secret scan plus a full-history check keep secrets out (see `docs/GITHUB_SETUP.md`). A private repo on Free would have no server-side enforcement.
10. **Reviewer identity** *(resolved)*: the reviewer is a separate agent that posts a fresh-eyes review comment; **a human approves and merges every PR**. GitHub forbids self-approval, so no second account is used and the ruleset does not require an approval.
11. **Who triggers review and merge** *(resolved)*: the orchestrator runs `scripts/review.sh <pr>` after a PR is marked ready; a **human** then reads the report and the CI result and approves and merges. `scripts/merge.sh` remains available to a human as a guarded merge helper.
