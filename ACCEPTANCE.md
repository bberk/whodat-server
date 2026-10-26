# ACCEPTANCE: Victory Points Fantasy Football Standings

> Status: DRAFT v0.1. Every criterion must be verifiable by an automated test unless marked (manual). Criteria IDs are stable; reference them in test names (e.g. `test_AC_VP_04_...`).
>
> Criteria tied to a **[DECISION]** or **[OPEN]** item in SPEC.md are marked and may change.

## 1. VP engine (pure function; unit tests, no I/O)

Input for a week: the list of teams with `team_id`, `points` (exact decimal), and `opponent_id` (or none for a bye). Output: per-team VP components and total.

| ID | Criterion |
|---|---|
| AC-VP-01 | H2H winner gets +1 for the H2H component; loser gets 0. |
| AC-VP-02 | If a matchup is tied, both teams get +0.5 for the H2H component. |
| AC-VP-03 | The top `floor(N/2)` scoring teams each get +1 top-half VP (no ties at the cutoff). |
| AC-VP-04 | The single highest scorer gets +1 for the high-score component. |
| AC-VP-05 | The single lowest scorer gets -1 for the low-score component. |
| AC-VP-06 | When k teams tie for the highest score, each gets `1/k` high-score VP. |
| AC-VP-07 | When k teams tie for the lowest score, each gets `-1/k` low-score VP. |
| AC-VP-08 | **[DECISION]** When teams tie across the top-half cutoff, they share equally the top-half points for the rank positions inside the cutoff. |
| AC-VP-09 | A team with no opponent (bye) gets no H2H component but still gets top-half/high/low components. |
| AC-VP-10 | Weekly total = H2H + top-half + high + low for every team. |
| AC-VP-11 | Score comparisons are exact: `123.40` equals `123.4`; values that differ only by float error are not treated as different. Scores are parsed from strings or Decimals, never compared as floats. |
| AC-VP-12 | Engine output is deterministic and independent of input ordering (property test: shuffling input yields identical per-team results). |
| AC-VP-13 | Property test: for any valid week, the sum of high-score VP is exactly +1, the sum of low-score VP is exactly -1, and the sum of H2H VP equals the number of completed matchups. |
| AC-VP-14 | The engine performs no I/O and imports nothing from the web, database, or provider layers (enforced by an import-boundary test or lint rule). |
| AC-VP-15 | A cup week (`h2h=False`) awards zero H2H VP to every team while the top-half, high-score, and low-score components are identical to a normal week. |

### 1.1 Worked examples (must be encoded as test fixtures)

**Example A: baseline with a tied high score (6 teams, 3 top-half slots)**

Matchups: A vs F, B vs E, C vs D.

| Team | Points | H2H | Top half | High | Low | Total |
|---|---|---|---|---|---|---|
| A | 120 | +1 (beat F) | +1 | +0.5 | 0 | **2.5** |
| B | 120 | +1 (beat E) | +1 | +0.5 | 0 | **2.5** |
| C | 100 | +1 (beat D) | +1 | 0 | 0 | **2** |
| D | 90 | 0 | 0 | 0 | 0 | **0** |
| E | 80 | 0 | 0 | 0 | 0 | **0** |
| F | 70 | 0 | 0 | 0 | -1 | **-1** |

(A and B are not playing each other. They tie for the highest score, so the high-score VP is split: 0.5 each. This is the 2.5 VP case from the original rules description.)

**Example B: tie across the top-half cutoff [DECISION] (6 teams, 3 top-half slots)**

Matchups: A vs E, B vs F, C vs D (C and D tied).

| Team | Points | H2H | Top half | High | Low | Total |
|---|---|---|---|---|---|---|
| A | 130 | +1 | +1 | +1 | 0 | **3** |
| B | 120 | +1 | +1 | 0 | 0 | **2** |
| C | 100 | +0.5 (tied matchup) | +0.5 | 0 | 0 | **1** |
| D | 100 | +0.5 (tied matchup) | +0.5 | 0 | 0 | **1** |
| E | 80 | 0 | 0 | 0 | 0 | **0** |
| F | 70 | 0 | 0 | 0 | -1 | **-1** |

(C and D occupy ranks 3 and 4; only rank 3 is inside the cutoff, so each gets 0.5 top-half VP. They also tied their own matchup, so each gets 0.5 H2H.)

**Example C: tied low score**

Two non-opposing teams tied for the lowest score each get -0.5 low-score VP.

**Example D: three-way tie for the high score**

Three tied teams each get exactly 1/3 high-score VP (tests must use exact fractions, not rounded decimals).

## 2. Standings and tiebreakers

| ID | Criterion |
|---|---|
| AC-ST-01 | Season VP for a team equals the sum of its weekly VP over all completed regular-season weeks. |
| AC-ST-02 | Teams are ranked by season VP descending. |
| AC-ST-03 | **[DECISION]** Teams tied on VP are ordered by H2H wins descending; H2H ties do not count as wins. |
| AC-ST-04 | Teams still tied are ordered by total points for descending. |
| AC-ST-05 | Teams tied on all three keys share the same rank number. |
| AC-ST-06 | Division standings group the same overall-ranked rows by division; the rank shown for each team is its overall league rank; no separate division-local ranking is computed. |
| AC-ST-07 | Overall rank is computed across all teams in the league for the season. |
| AC-ST-08 | **[DECISION]** Playoff weeks and incomplete weeks contribute no VP. |
| AC-ST-09 | Season totals that should be equal compare as equal even when built from fractional parts (e.g. 1/3 + 1/3 + 1/3 equals 1). |
| AC-ST-10 | A cup week changes no team's W-L-T record and awards no H2H VP, while points for and the top-half/high/low VP components still count toward the season. |
| AC-ST-11 | The weekly and cumulative VP series used by the chart include the cup week with its cup-week scoring. |

### 2.1 WAPDate standings

| ID | Criterion |
|---|---|
| AC-WD-01 | WAPDate uses three fixed, independent periods: weeks 1-4, 5-8 and 9-12. Weeks 13 and later are ignored, and no VP, wins or points for carry between periods. |
| AC-WD-02 | A period is offered when at least one of its weeks is completed. It is complete when the highest completed regular-season week is at least its end week; otherwise it is the current period. With no completed weeks no period is offered. For example, highest completed week 6 offers period 1 as complete and period 2 as current, and period 3 is absent. |
| AC-WD-03 | A team's period VP is the sum of its weekly VP for the period's completed weeks (cup-week aware), its wins are head-to-head wins in the period excluding the cup week, and its points for are the sum of its points in the period including the cup week. |
| AC-WD-04 | Period rows are ordered lowest first: VP ascending, then wins ascending, then points for ascending, then team name for stability. |
| AC-WD-05 | Greying applies only to the current period and uses VP and wins, ignoring points for. With `r = end_week - highest_completed_week`, a team's minimum VP is its current VP minus `r` and its minimum wins are its current wins; another team's maximum VP adds 3 per remaining non-cup week and 2 per remaining cup week, and its maximum wins add 1 per remaining non-cup week. A team is greyed when another team's maximum VP is below its minimum VP, or the maxima tie and that team's maximum wins do not exceed the team's minimum wins. |
| AC-WD-06 | A completed period shows the actual result with no greying. |
| AC-WD-07 | `GET /api/v1/leagues/{league_id}/seasons/{season}/wapdate` requires league membership (non-members get 404, unauthenticated requests get 401). It returns the offered periods with period number, start and end week, status (`complete` or `current`), counted weeks, and lowest-first rows with team id and name, VP as a string, wins, points for as a string, and an eliminated boolean. An empty season returns no periods. |
| AC-WD-08 | The standings page shows a WAPDate section below the cumulative VP chart. An accessible period toggle lists only the offered periods, labelled with their week range and complete/in-progress state, and defaults to the current period or the latest complete one. The selected period shows Team, VP, Wins and PF lowest first, with a sticky team column and horizontal scrolling inside the table container and no page-body sideways scroll at 360px. Eliminated teams are greyed and carry a text/accessible "Safe" marker, never colour alone. Loading, empty, and error states match the other data views. |

### 2.2 Playoff clinch designations

The clinch calculator is a pure domain function over exact VP, wins, divisions, cup week, playoff
field size, and remaining matchups. It never reads points for when proving a boundary.

| ID | Criterion |
|---|---|
| AC-PC-01 | In a finished two-division season, the better division winner is Z, the other division winner is Y, other playoff teams are X, and non-playoff teams are E. Each team has at most one designation. |
| AC-PC-02 | With zero or one division, the overall #1 seed is Z, other playoff teams are X, and Y is never used. |
| AC-PC-03 | Precedence is E, then Z, then Y, then X, otherwise no designation. A VP+wins tie at a decisive boundary is undecided because points for could change it; differing wins break a VP tie before points for is considered. A tie for a division's top record does not clinch that division. |
| AC-PC-04 | Remaining H2H pairings are respected: every non-cup game can be a home win, away win, or tie, contributing +1/+1/0.5 VP and wins only for a decisive winner. Direct H2H results that decide a late-season clinch or elimination are reflected rather than inferred from current totals. |
| AC-PC-05 | Cup weeks still include feasible top-half/high/low VP and current totals, but contribute no H2H VP and no win in any scenario. |
| AC-PC-06 | A bye is a valid remaining slot: it contributes rank VP extremes and no H2H VP or win. Missing, duplicate, unknown-team, self-team, wrong-week, or incomplete week coverage is not treated as a schedule. |
| AC-PC-07 | No designations are attempted when more than four regular-season weeks remain; with four or fewer, the same data can produce proven statuses. |
| AC-PC-08 | Missing or unusable playoff field size metadata yields only null designations. Existing seasons require a re-sync to acquire the field size; no value is guessed. |
| AC-PC-09 | Cheap feasible VP/wins bounds run before scenario enumeration. If a per-team node cap is exceeded, that team receives no designation; a failed search never produces a false badge. |
| AC-PC-10 | The calculator is deterministic and performs no I/O. Invalid settings, unsupported division shapes, and incomplete schedules return null designations for every affected team rather than partially guessing. |
| AC-PC-11 | The standings service computes designations once for the selected league season and puts the same `clinch` value on every overall row and on the same team's division row. The calculation uses remaining stored matchups, not another season's data. |
| AC-PC-12 | `app/domain/clinch.py` has 100% line and branch coverage in this feature's test suite. The conservative cross-team rank-VP relaxation and node-cap behavior are documented so a withheld badge is understood as intentional. |

### 2.3 Elo history

The Elo model is pure and deterministic. Expected numbers below use exact `Decimal` arithmetic;
the API serializes ratings and changes as strings.

| ID | Criterion |
|---|---|
| AC-Elo-01 | Expected score is `E_a = 1 / (1 + 10 ** ((R_b - R_a) / 400))`; `E_a + E_b = 1`, and equal ratings give 0.5. Both teams receive the same signed delta, so every decisive matchup is exactly zero-sum. A win uses S = 1, a tie S = 0.5, a loss S = 0. |
| AC-Elo-02 | The base K factor is configurable and scales the update: at equal ratings and no margin bonus, a win moves the rating by K / 2 (default K = 24 gives +12 / -12). |
| AC-Elo-03 | Effective K is `K * (1 + margin_weight * min(\|margin\|, margin_cap) / margin_cap)`. With defaults, a 10-point margin uses K = 25.2, a 50-point margin uses K = 30, and any margin above 50 uses the same capped K = 30. A tie has margin 0 and uses the base K. |
| AC-Elo-04 | Before each new stored season, a returning franchise moves toward the starting rating: `R' = start + (R - start) * (1 - season_regression)`. With the default 1/3, 1600 becomes 1566.67 and 1400 becomes 1433.33. A franchise that misses stored seasons applies one regression per missed season boundary when it returns. |
| AC-Elo-05 | Every franchise starts at the configured starting rating (default 1500), including one that first appears mid-history. Its series has leading nulls for seasons before it existed and its first non-null point is the rating after its first rated week. |
| AC-Elo-06 | Ratings follow the franchise slot keyed by `team.external_id` across seasons, not the owner and not the season-specific team id. A rename or owner change keeps the rating; the API returns the latest name/owner, earlier names as aliases, and a stable `team_key`. Duplicate current names are disambiguated in the UI. |
| AC-Elo-07 | In `actual_schedule` mode each completed regular-season head-to-head matchup updates both teams in deterministic order; byes update nobody; cup weeks are skipped entirely (flat series point, no rating change); playoffs and incomplete weeks are excluded. |
| AC-Elo-08 | In `round_robin` mode every completed regular-season week, including cup weeks, compares every unordered pair of teams from that week's start-of-week ratings and applies each team's average pairwise delta. The result is independent of team or score input order and remains zero-sum. |
| AC-Elo-09 | A cup week is skipped in actual-schedule mode but rated in round-robin mode. Its chart slot is marked `is_cup_week`, and the series is flat in actual schedule. |
| AC-Elo-10 | Playoff weeks, weeks with any incomplete matchup, and bye matchups do not rate. A week with no eligible result still appears as a completed chart slot only when it is a completed regular-season week; otherwise it is omitted. |
| AC-Elo-11 | History is computed on read from stored seasons, teams, matchups, and scores. Adding a season recomputes it in chronological order; deleting a season removes its teams' points and recomputes later ratings without leaving stale data. |
| AC-Elo-12 | The history response exposes ordered seasons, one `weeks` entry per completed regular-season week (`season`, `week`, `is_cup_week`, `is_season_start`, `rated`), season boundaries with chart indices, and per-team aligned series. `null` means the team was absent from that season. Peak/low/current/changes use exact values internally; peak and low include the starting rating, label it as "start" when it is the extreme, and season change is measured from the team's post-reset baseline. Teams are ordered by first season then `team_key` for stable styling. |
| AC-Elo-13 | `elo_config` stores one optional row per league with `starting_rating`, `k_factor`, `margin_weight`, `margin_cap`, and `season_regression`. No row returns the documented defaults. Migration 0008 creates the table on SQLite and Postgres and downgrades cleanly. |
| AC-Elo-14 | `GET /api/v1/leagues/{league_id}/elo-history?mode=actual_schedule\|round_robin` requires league membership (401 unauthenticated, 404 non-member or unknown league), validates the mode and a positive league id with a structured 422, and returns 200 with an empty history (empty arrays) when there are no rated weeks. Ratings and changes are JSON strings, never numbers, and no credential material appears. |
| AC-Elo-15 | `GET /api/v1/leagues/{league_id}/elo-config` is admin-only for the settings form and returns the saved values or the defaults; `PUT` is admin-only and accepts the five values with ranges start 1000-2000, K 1-100, margin weight 0-1, margin cap 1-200, regression 0-1. Both return 401/403/404 correctly, use structured validation errors, and never echo credentials. Saving settings changes subsequent history reads without a snapshot table. |
| AC-Elo-16 | The History tab appears in the primary nav next to Standings and Owner for every league member (Admin remains admin-only), routes to `/leagues/:leagueId/history`, is protected, and hides the shell season picker. It has a mode control for Actual schedule and Round robin with an accessible explanation, switching refetches, loading/empty/error states, and no colour-only signalling. |
| AC-Elo-17 | The History chart draws one line per franchise from the first stored season, season boundary rules and labels, cup-week markers in actual-schedule mode, legend controls that toggle and select series, a selected-team emphasis, an accessible summary, and a `<details>` data-table alternative. A season filter defaults to All history. |
| AC-Elo-18 | The current-ratings table shows team, current rating rounded to a whole number, change this week and this season with exactly two decimals and an explicit sign, peak, low, and owner, sorted by current rating. At 360px it scrolls inside its region with a sticky team column and the page body never scrolls sideways. |
| AC-Elo-19 | The admin page has an Elo settings section with labelled fields for starting rating, K factor, margin weight, margin cap, and season regression. Each field has an accessible tooltip that works on hover and keyboard focus. "Recalculate Elo history" validates ranges, saves through the API, shows saving, success, and error states, and invalidates/refetches the History view. The section does not interfere with the Seasons, Members, Invites, or delete-league sections. |
| AC-Elo-20 | The History page and the admin Elo settings section pass an axe scan with no serious or critical violations; controls are keyboard operable and the chart summary, table caption, and cup/week/season markers are exposed as text. |

### 2.4 Playoff odds

The playoff-odds simulator is pure and additive. It starts from the exact current totals the
standings page shows, simulates only the remaining regular-season weeks, and never writes data.

| ID | Criterion |
|---|---|
| AC-PO-01 | A pure domain simulator accepts exact current totals, divisions, settings, and the remaining stored schedule, and returns per-team playoff, bye, division-title, and championship counts plus diagnostics. Scores are integer cents and VP is integer ticks; no `float` is used for either. |
| AC-PO-02 | Every simulated week's VP equals `compute_week_vp` exactly, component by component, including H2H ties, top-half cutoff ties, high/low splits, byes, and cup weeks (property test). |
| AC-PO-03 | The sampler shrinks a team's deviation from the league mean with three pseudo-games, draws a team's own residuals with probability `min(1, w) * n / (n + 4)` when `n >= 2` (cap at 1, where `w` is the team-strength weight of AC-PO-15), otherwise the pooled pool, and uses week-centred residuals with no team deviation when fewer than two counted weeks exist or no team has two observations. Outliers are kept and a team with no history uses the pooled residuals. |
| AC-PO-04 | Division winners are seeded first in VP/wins/points-for order, followed by the remaining teams in that order. The bye count is `min(divisions, max(0, next_power_of_two(P) - P))`, and byes go only to the top division winners. Exactly `playoff_team_count` teams qualify in every simulated season; a missing, out-of-range, or too-small playoff field is unavailable rather than guessed. A field and bye count that cannot form a complete bracket, such as an odd number of non-bye teams, is unavailable with reason `invalid_playoff_bracket` instead of inventing a bye. |
| AC-PO-05 | The final table ranks by VP, H2H wins, points for, then team name and id. A level VP+wins tie is resolved by points for, which may differ from the conservative clinch designation. Division-title probability is reported separately and only division winners receive it. |
| AC-PO-06 | The simulator is deterministic for a given input and seed. The API runs exactly the requested number of iterations (1-100,000, subject to the role cap of AC-PO-18), returns the seed, and reproduces identical counts for the same input and seed. A finished regular season still projects the requested number of playoff brackets from its final seeds; it is never reported as `iterations = 0`. |
| AC-PO-07 | `GET /api/v1/leagues/{league_id}/seasons/{season}/playoff-odds` is member-only (401 unauthenticated, 404 non-member or unknown league), returns the documented JSON with playoff, bye, division-title, and championship probabilities as fixed four-decimal strings with Wilson 95% intervals, validates `iterations`, `seed`, and a decimal `strength_weight` (0-10) with structured 422s that never echo the submitted value, sets `Cache-Control: private, max-age=300`, and is rate limited with 429 and `Retry-After`. A stored season that is not the league's latest stored season is rejected with a structured 409 `season_not_current` before any simulation input is read, cached, or simulated; an unknown league or unstored season remains a structured 404. |
| AC-PO-08 | No completed weeks, a missing playoff field, an incomplete or inconsistent remaining schedule (including a playoff week inside the regular season), an unsupported division shape, an invalid playoff bracket, and a finished regular season each produce the documented `status`/`reason`/`iterations` response. Corrupt season settings still return the standings-style structured 400. |
| AC-PO-09 | Results are cached in process per `(league, season, input digest, iterations, seed, team-strength weight, model version)`. A score, schedule, cup-week, playoff-field, division, team-name, current-total, or team-strength-weight change invalidates the entry; `last_refreshed_at` alone does not, and a second identical request does not run the simulator again. |
| AC-PO-10 | For a fixture with a complete proof, every team with clinch `X`, `Y`, or `Z` has playoff probability 1.0000, every `E` team has 0.0000, and a `Y`/`Z` team has bye probability 1.0000 when the bracket awards byes. |
| AC-PO-11 | The standings page renders a Playoff odds section below the WAPDate standings only when the selected season is the league's latest stored season; a prior season renders no section, no placeholder, and makes no playoff-odds request. The section shows team, division, playoff %, bye %, championship %, and the uncertainty range; playoff, bye, and championship headers sort on the client and the active header carries `aria-sort`; loading, unavailable (per reason), empty, error, low-confidence, and finished-season states are present; the table scrolls inside its region with a sticky team column and no page-body sideways scroll at 360px; and colour is never the only signal. |
| AC-PO-12 | `domain/predictions.py` has 100% line and branch coverage; backend total stays at or above 85%; frontend coverage thresholds are unchanged; and `docs/openapi.json` plus generated frontend types include the endpoint. |
| AC-PO-13 | All simulation adjustment controls live in the standings Playoff odds section, which simulates only the current season and offers no way to target a prior season. It has iteration, team-strength weight, and optional seed fields and a Run action. The admin page has no playoff-odds section, component, or control. Running the form calls the playoff-odds endpoint with those values, never the season refresh or the provider, shows busy, error, unavailable, and ready states, rejects invalid values before requesting the API, and displays the same per-team table as the standings page without changing stored data or the shared data version. |
| AC-PO-14 | Playoff odds are available only for the league's current season, defined as the maximum stored `league_season.season` and matching the existing league-refresh current-season rule. The API rejects every other stored season without simulating, and the standings page hides the section for a prior season. |
| AC-PO-15 | The simulation accepts an optional team-strength weight `w` in 0-10 inclusive with exact decimals (at most 18 decimal places, no binary float), defaulting to 1. The score model uses `base_t = mu_bar + w * delta_t` and scales each team's own-residual probability to `min(1, w) * n_t / (n_t + 4)` capped at 1. At `w = 1` the regular-season score model, its draw order, and its playoff/bye/division counts are unchanged from the previous model; the projected bracket uses a separate derived draw stream, so championship probabilities are new. At `w = 0` all teams draw one distribution (grand mean plus pooled residuals), so remaining matchups are effectively even and team strength creates no edge while current VP, wins, and points for still decide seeding; decimals interpolate, and `w > 1` increases the stronger team's projected advantage. The weight is part of the input digest, the cache key, and the response metadata, and the model version is bumped. A value outside 0-10, non-finite, or unparsable is a structured 422 without the submitted value echoed. Both frontend and backend accept any castable numeric string, including `.25`, `1.`, and `0.25`, with no leading-zero or number-step requirement; the backend parses it as an exact `Decimal`. |
| AC-PO-16 | After the regular season, the qualifiers are seeded and a single-elimination bracket is projected with reseeding after every round: the highest remaining seed plays the lowest, byes apply only in the first round to the top `bye_count` seeds, each round samples fresh scores from the same team-strength and residual model, the higher score wins, and an exact tie goes to the higher seed. Real stored playoff matchups are excluded. Each simulation produces exactly one champion. |
| AC-PO-17 | Each team reports a championship count and probability with the same Wilson 95% interval treatment as playoff, bye, and division-title probabilities. Across any run the championship counts sum to the iteration count, and a finished regular season still projects its bracket rather than reporting a deterministic champion. |
| AC-PO-18 | Iterations are accepted from 1 to 100,000. An authenticated regular member may request at most 10,000; an authenticated admin may request up to 100,000. The backend enforces the role cap from the authenticated role and returns a structured 403 above it, the frontend shows the cap for the signed-in role, and a value outside 1-100,000 is a structured 422. The default is 10,000. |
| AC-PO-19 | The standings Playoff odds section shows the simulation controls (iterations, team-strength weight, optional seed, Run) with accessible labels and help text, the correct iteration maximum for the role, busy and validation states, and no page-body sideways scroll at 360px. The admin page no longer renders a playoff-odds section, and its tests and component are removed. |

## 3. Data sync and storage

| ID | Criterion |
|---|---|
| AC-DB-01 | After a sync, the database contains the league, owners, teams (with season and division), matchups, and scores for the requested season. |
| AC-DB-02 | Running the same sync twice produces identical database contents (no duplicates, no changed rows). |
| AC-DB-03 | If a provider reports a changed score for an already-synced week, the score is updated and VP for that whole week is recomputed for all teams. |
| AC-DB-04 | Each Score row stores total VP and the component breakdown (h2h, top-half, high, low). |
| AC-DB-05 | The same test suite passes against both engines: SQLite locally and in the pre-push hook, Postgres in CI. |
| AC-DB-06 | One head round-trip plus `alembic check` per engine; the downgrade path of a new revision is exercised once in its PR, not forever in the suite. |
| AC-DB-07 | Sync tests run entirely from recorded fixtures; the test suite makes no live ESPN calls. |
| AC-DB-08 | ESPN credentials (`espn_s2`, `SWID`) never appear in logs, error messages, API responses, or the repository. |
| AC-DB-09 | Each `league_season` stores an optional `cup_week` (nullable; `null` means no cup week). Sync preserves it, recompute stores `vp_h2h = 0` on that week, and changing it recomputes the season from stored data in the same operation. |
| AC-DB-10 | Each `league_season` stores a nullable `last_refreshed_at` timestamp, surfaced as an ISO instant. A successful provider-backed sync (add league, add season, per-season refresh, or CLI sync) sets it; a provider-free recompute or cup-week edit never changes it. Existing rows are `null` ("Never") after migration 0007. |
| AC-DB-11 | A default sync with a known regular-season length stores every regular-season matchup, including future incomplete pairings, and stores the provider's `playoff_team_count` in that season's metadata. Future sides with no provider points create no score row and earn no VP; an explicit bye is retained. |
| AC-DB-12 | Syncing an incomplete week reconciles it against the provider: matchups whose home slot no longer exists are deleted, stale removed-team scores are deleted, current pairings and home/away swaps are inserted or updated, and a moved team may become a bye. Completed-week matchup and score data is not reconciled by a future schedule edit. |

## 4. Provider abstraction

| ID | Criterion |
|---|---|
| AC-PR-01 | A `LeagueProvider` interface exists; the sync service depends only on it and on normalized data types. |
| AC-PR-02 | A `FakeProvider` (in-memory) exists and the entire sync → VP → standings pipeline is tested end to end using it, with no ESPN code involved. |
| AC-PR-03 | No module outside `providers/espn/` imports `espn_api` or contains ESPN-specific logic (enforced by an import-boundary test or lint rule). |
| AC-PR-04 | Adding a second provider requires no changes to the engine, models, API, or frontend. (Demonstrated by the `FakeProvider` being registered purely through the provider registry.) |

## 5. Accounts and authorization

| ID | Criterion |
|---|---|
| AC-AU-01 | A visitor can sign up only with a valid, unexpired shared invite code. Signup validates the submitted code against the invite's stored hash (the raw code is never stored); every invite carries the role (`admin` or `member`) assigned to the new account and defaults to a 7-day expiry. An **admin** invite is league-less; a **member** invite is bound to exactly one league and grants that membership at signup. An invite can be used by multiple invitees while unexpired. The raw code is shown only once when an admin creates the invite and is never retrievable afterwards; regenerating means creating a new invite. Missing, unknown, or expired codes are rejected. |
| AC-AU-02 | Duplicate emails are rejected case-insensitively (emails are stored lowercase). |
| AC-AU-03 | Passwords are stored only as salted argon2id hashes; no plaintext password appears in the database or logs. |
| AC-AU-04 | Valid credentials log the user in; invalid credentials return the same generic error for an unknown email and a wrong password (no user enumeration). |
| AC-AU-05 | Users and leagues are many-to-many: a user can hold memberships in multiple leagues, a membership is unique per (user, league), and a duplicate join is rejected. A member invite creates its membership automatically at signup; an existing member joins an additional league only by redeeming a valid member invite for that league, never by supplying a bare `espn_league_id`. |
| AC-AU-06 | Only an admin can add a league with credentials, and no invite is required. The admin supplies `espn_league_id`, an optional season, and optional ESPN_S2/ESPN_SWID; the backend validates by constructing an ESPN league object before storing anything. On success it stores the league, the membership, the encrypted credentials, and syncs the requested season; on validation failure it stores nothing. |
| AC-AU-07 | League credentials are encrypted at rest with AES-256-GCM under a key from `LEAGUE_CREDENTIALS_KEY`; they are decrypted only on the provider call path and are never returned by the API or written to logs or error messages. |
| AC-AU-08 | A member cannot add a league by `espn_league_id` and cannot supply credentials; such attempts are rejected and store nothing. A member joins a league only by redeeming a valid, unexpired member invite for that league. |
| AC-AU-09 | A member whose membership holds credentials can trigger a league-wide refresh; refresh is rate limited per league and per user, and a member without credentials cannot refresh. The UI's only refresh control is the admin seasons table's per-season refresh. |
| AC-AU-10 | Every league-scoped endpoint enforces membership server-side: unauthenticated requests return 401, and a non-member requesting another league's data gets 403 or 404, never data. |
| AC-AU-11 | Auth endpoints (signup and login) are rate limited; a test demonstrates throttling after repeated requests or failures. |
| AC-AU-12 | After joining, a user can set the owner association only on their own membership, choosing from that league's owners; another user's membership cannot be changed. |
| AC-AU-13 | League credentials exist only on a `user_league` membership; there is no environment `ESPN_S2`/`ESPN_SWID` credential path, and API request handling never reads credential environment variables. The CLI syncs using a member's stored credentials selected explicitly with `--as-email`. |
| AC-AU-14 | A user who signs up with an admin invite has no league; the UI forces the mandatory create-your-league step (ESPN league id, season, ESPN_S2/ESPN_SWID) and standings are unreachable until it succeeds. Completing it creates the league and the user's membership. |
| AC-AU-15 | A user who signs up with a member invite already holds that league's membership and reaches its standings without the create-league step. |
| AC-AU-16 | Redeeming a member invite for an additional league creates exactly one membership; an expired, unknown, or wrong-role (admin) invite is rejected and creates nothing. |
| AC-AU-17 | Invite creation rejects a member invite with no league and an admin invite with a league; the role/league invariant is enforced at creation. |
| AC-AU-18 | Only a global admin who holds a membership in an existing league can add a season to it. The season must not already be stored, and the call syncs immediately using the caller's own stored league credentials (the same model as refresh), with no fallback to another member's credentials or the environment. A non-admin member gets 403, a non-member gets 404, a duplicate season gets 409, and a caller without stored credentials is rejected. The write is atomic: a provider failure leaves no partial league or season rows, and no credential value or provider exception text appears in a response or log. A successful add sets that season's `last_refreshed_at`. |
| AC-AU-19 | `GET /api/v1/leagues/{league_id}/members` lists every account with a membership in the league, identified by email (the application has no username), with its role, optional owner association, and whether it holds stored credentials. It is admin-only: a non-admin member gets 403, a non-member gets 404, and an unauthenticated request gets 401. No password hash, credential value, or invite hash appears in the response. |
| AC-AU-20 | `DELETE /api/v1/leagues/{league_id}/members/{user_id}` removes exactly that user's membership in this league; the membership row's owner association and stored credentials go with it, while the account and its memberships in other leagues remain. Admins may remove themselves or another admin, but the request is refused with 409 and no change when it would leave the league with zero admin members. A non-admin member gets 403; a non-member or a target without a membership here gets 404. |
| AC-AU-21 | `POST /api/v1/leagues/{league_id}/invites` creates a `member` invite bound to this league or a league-less `admin` invite; a member invite without this league and an admin invite with one are impossible through this endpoint. Expiry defaults to seven days and is bounded to 1..3650 days. Only the code hash is stored, and the raw code is returned exactly once, by this endpoint only, never by another endpoint. It is admin-only (non-admin member 403, non-member 404, unauthenticated 401) and returns 201 with the code, role, league id or null, and expiry. |
| AC-AU-22 | `DELETE /api/v1/leagues/{league_id}` deletes this league and all of its data in one transaction: the league, its seasons, teams, owners, matchups, scores, memberships, Elo settings, and invites bound to it. User accounts, league-less admin invites, and other leagues are untouched. Deleting a league that never had Elo settings also succeeds. It is admin-only (non-admin member 403, non-member 404, unauthenticated 401). Child-first deletion satisfies foreign-key enforcement on both SQLite and Postgres. |
| AC-AU-23 | `GET /api/v1/leagues/{league_id}/seasons/settings` returns every stored season, ascending, with `season`, `cup_week`, `regular_season_length`, and `last_refreshed_at` (ISO or null) for an admin member. A member without the admin role gets 403, a non-member gets 404, and an unauthenticated request gets 401. It reads stored rows and never contacts the provider. |
| AC-AU-24 | `POST /api/v1/leagues/{league_id}/seasons/{season}/refresh` syncs exactly one already-stored season through the provider with the caller's own stored credentials and returns its season and weeks synced. It is admin-only (non-admin 403, non-member or unknown season 404, unauthenticated 401), requires stored credentials (403), uses a separate configurable per-season refresh bucket (default: no per-league interval and 60 per user per hour, so consecutive season refreshes are allowed; 429 with Retry-After when that bucket is exhausted), sets `last_refreshed_at` on success, and never creates or duplicates a league or season. A failure changes neither data nor the timestamp. |
| AC-AU-25 | `DELETE /api/v1/leagues/{league_id}/seasons/{season}` deletes exactly that season's `league_season` row, teams, matchups, and scores in one transaction, keeping the league, owners, memberships, invites, and every other season. It returns 204 with no body and is admin-only (non-admin 403, non-member or unknown season 404, unauthenticated 401). The delete is atomic and child-first on SQLite and Postgres. |

## 6. API

| ID | Criterion |
|---|---|
| AC-API-01 | The endpoints in ARCHITECTURE.md exist and match the published OpenAPI spec. CI regenerates OpenAPI and fails if it differs from `docs/openapi.json`; generated TS types compile. |
| AC-API-02 | The standings response for a known fixture league matches a checked-in golden JSON file exactly (ranks, VP, tiebreak ordering, weekly VP). |
| AC-API-03 | The cumulative VP response for a team at week W equals the sum of its weekly VP for weeks 1..W. |
| AC-API-04 | Invalid inputs (unknown season, week out of range) return 4xx with a structured error body, never a 500. |
| AC-API-05 | Standings for a 12-team, 18-week season respond in under 500 ms (p95) against SQLite in a local benchmark test. |
| AC-API-06 | `POST /api/v1/leagues/{league_id}/seasons` accepts `{season: int}` with a year from 2000 to 2100 and returns 201 with the league id, season, and weeks synced. Admin-only, membership, duplicate-season, missing-credential, and provider failures map to structured 4xx responses, and the committed OpenAPI document includes the endpoint. |
| AC-API-07 | `GET` and `PUT /leagues/{league_id}/seasons/{season}/cup-week` require league membership (non-members get 404) and `PUT` requires the admin role (403). `GET` returns season, cup_week, and regular_season_length. `PUT` accepts a week in 1..regular_season_length or `null` to clear it, rejects missing, zero, negative, and out-of-range values with a structured 4xx, persists the value, and recomputes the league's stored VP in the same operation. |
| AC-API-08 | The league-admin endpoints `GET /leagues/{league_id}/members`, `DELETE /leagues/{league_id}/members/{user_id}`, `POST /leagues/{league_id}/invites`, and `DELETE /leagues/{league_id}` exist, match the committed OpenAPI document, and use the existing structured 401/403/404/409 error shapes. The two delete routes return 204 with no body. |
| AC-API-09 | `GET /leagues/{league_id}/seasons/settings`, `POST /leagues/{league_id}/seasons/{season}/refresh`, and `DELETE /leagues/{league_id}/seasons/{season}` exist, match the committed OpenAPI document, and use the structured 401/403/404/409/422 error shapes with no credential, token, or provider exception text. `docs/openapi.json` and the generated frontend types are regenerated with them. |
| AC-API-10 | Every standings row, in both `overall` and `divisions`, includes `clinch` as one of `"Z"`, `"Y"`, `"X"`, `"E"`, or `null`. The committed OpenAPI document and generated frontend types include the field, and authenticated responses serialize the same value for a team in both places. |

## 7. Frontend

| ID | Criterion |
|---|---|
| AC-FE-01 | A logged-in user sees the overall standings table with rank, team, owner, season VP, W-L-T, points for, and a VP column per week. |
| AC-FE-02 | Division standings render as one table per division; each row shows the team's overall league rank. |
| AC-FE-03 | The cumulative VP chart shows one line per team with week on the x-axis and cumulative VP on the y-axis; values match the API. |
| AC-FE-04 | Selecting a team highlights it in both the chart and the table; teams can be toggled in the chart. |
| AC-FE-05 | The layout is usable at 360px, 768px, and 1280px widths: no horizontal scrolling of the page body, wide tables scroll within their container with the team column pinned (Playwright screenshot tests at those widths). Exactly three widths in one Playwright spec; no per-component visual snapshots. |
| AC-FE-06 | Loading, empty (no data yet), and error states are shown for each data view. |
| AC-FE-07 | Automated accessibility check (axe) reports no serious or critical violations on the login and standings pages. |
| AC-FE-08 | Unauthenticated users are redirected to login; after login they return to the page they requested. |
| AC-FE-09 | (manual) A human reviewer confirms the UI looks modern and polished on a real phone and a desktop browser. |
| AC-FE-10 | An admin can add a season for the selected league from the admin page's `+` action: a dialog with a labelled whole-year input (2000-2100, required, defaulting to the current year), an Add action with a loading state, clear success and error messages, and no colour-only signalling. On success the league's seasons refresh, the seasons table refetches, and the newly added season is selected. |
| AC-FE-11 | `/leagues/:leagueId/admin` renders a `League admin` page for admins with the `Admin` nav item visible only when the signed-in user is an admin and a league is selected; non-admins are redirected to `/`. The page hosts one seasons table with a row per stored season and columns for season year, cup-week dropdown, last refreshed, refresh, and delete. The cup-week dropdown offers `No cup week` or weeks 1..regular_season_length for that row, saves immediately through the API (no separate Save button), recomputes from stored data without a provider call, and shows a per-row saving state, success text, and error text with labelled controls and no colour-only signalling. |
| AC-FE-12 | The shell's season picker appears on the standings route only; it is absent on `/leagues/:leagueId/owner` and `/leagues/:leagueId/admin`, while the league switcher remains on both. There is no refresh button in the app shell on any page; the admin seasons table is the only refresh mechanism in the UI. |
| AC-FE-13 | The admin page's Members section lists every league member by email with role, owner association, and credential status, with loading, empty, and error states and an accessible table. Removing a member opens a confirmation that names the member, warns when the removal is the caller's own membership, and warns that refresh stops working when the member is the only one with stored credentials. The last admin cannot be removed. After removing yourself the page returns to the standings and the league list refreshes. |
| AC-FE-14 | The admin page's Invites section generates a member invite (bound to this league) or a league-less admin invite, defaults the expiry to 7 days, and shows the raw code exactly once with a copy control and a note that it cannot be retrieved again. |
| AC-FE-15 | The admin page's Danger zone deletes the league only after the admin types its exact name; the action is visually distinct and confirmed, and on success the league list refreshes and the app returns to the standings/empty state. |
| AC-FE-16 | Each seasons-table refresh button syncs only that row's season through the provider with the caller's stored credentials, shows a per-row progress state and any structured error (including the 429 Retry-After window), and updates the row's last-refreshed value on success. Last refreshed displays a readable local value from the ISO timestamp, or `Never` when null. The table scrolls inside its own container with a sticky season column and no page-body sideways scroll at 360px; every control is keyboard operable with an accessible name. |
| AC-FE-17 | Each seasons-table delete control is an X with an accessible name, opens a confirmation dialog naming the season, deletes only that season's data, and on success removes the row and refreshes the shared season and standings lists. If the deleted season was selected, the app selects the latest remaining season or none. |
| AC-FE-18 | The standings page keeps the `Overall standings`, `Division standings`, `Cumulative VP by week`, and `WAPDate standings` headings, their tables/chart, the meta line under the page title, and all accessibility labels/captions, but shows no instructional subheader paragraph under a section and no footer note about decimal strings. |
| AC-FE-19 | The overall and division standings show a small designation beside the team for Z/Y/X/E, with visible letter, tooltip, and accessible name spelling out `"Z — top seed"`, `"Y — division winner"`, `"X — clinched playoff berth"`, or `"E — eliminated"`. The team button keeps the team name as its accessible name, a text legend for all four sits near the overall table, colour is not the only signal, the sticky team/rank columns remain, and the page still fits 360px without body sideways scroll. |

## 8. Repository and delivery

| ID | Criterion |
|---|---|
| AC-DX-01 | A fresh clone can run the app locally following README steps only (or `docker compose up`). |
| AC-DX-02 | CI runs `pre-commit` on all files, backend tests (against Postgres), and frontend lint, type check, tests, and build on every pull request and every push to `main`, and they all pass on `main`. |
| AC-DX-03 | `backend/src/app/domain/vp_engine.py` and `backend/src/app/domain/standings.py` each have 100% line and branch coverage; no other module has a per-file target. |
| AC-DX-04 | Backend total coverage is at least 85% lines and branches; no PR reduces it by more than 1.0 percentage point. |
| AC-DX-05 | No secrets are committed; `.env.example` documents every required variable. |

## 9. Development workflow and quality gates

| ID | Criterion |
|---|---|
| AC-WF-01 | `.pre-commit-config.yaml` exists and `pre-commit install --hook-type pre-commit --hook-type pre-push` installs the commit and push hooks. There is no post-commit hook. |
| AC-WF-02 | The commit-time hooks include: ruff lint (with auto-fix), ruff format, mypy, eslint, tsc, prettier, secret scanning, and file-hygiene checks (whitespace, EOF, YAML/TOML/JSON validity, merge-conflict markers, large files, private keys). |
| AC-WF-03 | A commit containing a ruff violation (or a failing mypy, eslint, or tsc check) is rejected by the hooks. (Verified once by hand during M0 with a throwaway branch.) |
| AC-WF-04 | A commit made directly on `main` is rejected by the `no-commit-to-branch` hook. |
| AC-WF-05 | Pre-push runs the fast suite and excludes tests marked `slow`/`postgres` and Playwright; CI runs the full suite. |
| AC-WF-06 | CI runs `pre-commit run --all-files`, so a change that bypassed the local hooks still fails the PR. |
| AC-WF-07 | Pushing is an explicit step: committing runs no hook that pushes or opens a PR, and the author agent pushes its branch with `scripts/ship.sh` before opening or updating the pull request. |
| AC-WF-08 | `scripts/ship.sh` refuses to run on `main`. |
| AC-WF-09 | `scripts/ship.sh --ready` marks the PR ready for review and adds the `ready-for-review` label. |
| AC-WF-10 | `scripts/review.sh <pr>` runs the reviewer in a new session on a clean worktree checked out at the PR head, with the reviewer definition taken from `main` rather than from the PR; the reviewer never sees the author's context. |
| AC-WF-11 | The review is submitted as a GitHub review comment on the PR's current head commit, stating a verdict (approved or changes requested) and listing the blocking issues, the non-blocking suggestions, and what was verified. |
| AC-WF-12 | The reviewer cannot modify files, push, or merge (enforced by its permission configuration). |
| AC-WF-13 | `scripts/merge.sh <pr>` merges and deletes the branch only when the PR is open, not a draft, and all CI checks passed; it rebases by default and squashes with `--squash` (there is no merge commit: the ruleset requires linear history). It refuses a PR that changes governance files unless run with `--allow-governance`. Each unmet condition is tested and blocks the merge (synthetic-data tests of the gate logic). |
| AC-WF-14 | An independent review of an earlier commit does not count for a newer head: the review records the head commit it reviewed, and a push after a review requires a new review. |
| AC-WF-15 | A PR that changes governance files (`AGENTS.md`, `SPEC.md`, `ACCEPTANCE.md`, `ARCHITECTURE.md`, `.opencode/`, `.github/`, `scripts/`, `.pre-commit-config.yaml`) is not merged by `scripts/merge.sh` without `--allow-governance`, and only a human merges it. |
| AC-WF-16 | Every PR gets a single combined coverage comment covering the backend and the frontend, updated in place on each push, also written to the CI job summary. |
| AC-WF-17 | The coverage comment reports lines and branches for the backend, and lines, statements, functions, and branches for the frontend, and lists the least-covered files. It also reports the change from the base branch and the two named 100% modules separately. |
| AC-WF-18 | CI fails below 85% total, below 100% for the two named modules, or below the frontend thresholds; it does not enforce other per-file targets. |
| AC-WF-19 | (manual) The repo is configured per `docs/GITHUB_SETUP.md`: squash and rebase merges (linear history, so no merge commits), branches deleted on merge, `ready-for-review` label exists, Actions token read-only. |
| AC-WF-20 | (manual, requires a public repo or paid plan) The `main` ruleset rejects direct pushes, force-pushes, and merges without passing required checks, and requires a pull request; required check names match the real CI job names. (No approval is required: a human approves and merges.) |
| AC-WF-21 | (manual) One trivial change goes through the whole loop successfully: commit, draft PR, ready, independent agent review, human merge (rebase or squash). A second trivial change with a deliberate defect gets a changes-requested review. |
| AC-WF-22 | The author agent opens the draft PR with `gh` run as the App identity (`scripts/bot-identity.sh run gh pr create --draft`) with a filled-in description (title follows the commit rules; every template section filled; no instructions to the reviewer) and keeps the body current; `scripts/ship.sh` never creates a PR. The procedure is `.opencode/pull-requests.md`. |
| AC-WF-23 | `scripts/cleanup.sh [--dry-run] [branch ...]` deletes local `agent/*` branches whose pull request is merged and removes the worktree each is checked out in. It keeps `main`/`master`, the current branch, a branch with no merged PR, a branch that moved past the merged head, and a branch whose worktree has changes; `--dry-run` changes nothing; `scripts/merge.sh` runs it for the PR it merged; it reports and keeps branches when GitHub cannot be queried. Tested with synthetic `gh` payloads (AC-WF-23 tests). |

## 10. End-to-end smoke test

A single Playwright test using the `FakeProvider` and a seeded league must: sign up with an invite code
→ join the league → set the owner association → view overall standings → view division standings →
see the cumulative VP chart, with every number matching the golden fixture.

## 11. Definition of done for the whole project

All criteria above pass in CI, all **[OPEN]** questions in SPEC.md are resolved or explicitly deferred, and the owner has verified AC-FE-09, AC-WF-19 through AC-WF-21, and a real ESPN sync against their actual league (manual).
