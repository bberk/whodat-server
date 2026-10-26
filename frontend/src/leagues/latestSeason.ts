/**
 * The league's current season is its latest stored season.
 *
 * This mirrors the API rule: `league_service._current_season` and the playoff-odds endpoint use the
 * maximum stored `league_season.season`, so the standings page and the admin simulator agree about
 * which season may show or run odds.
 */
export function latestSeason(seasons: readonly number[]): number | null {
  return seasons.length === 0 ? null : Math.max(...seasons);
}
