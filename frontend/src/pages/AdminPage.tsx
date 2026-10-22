import { useEffect } from "react";
import { Navigate, useParams } from "react-router-dom";

import { EmptyState } from "../components/DataStates";
import { AddSeasonSection } from "../leagues/AddSeasonSection";
import { useLeague } from "../leagues/LeagueContext";
import { CupWeekSection } from "./CupWeekSection";

/**
 * League administration page (AC-FE-10 add season, AC-FE-11 cup week).
 *
 * The route is wrapped in the admin guard, so non-admins are redirected before this page renders.
 * Both season-scoped sections live here: adding a stored season and choosing the season's cup week.
 * Each section owns its form, validation, and loading/error/success states.
 */
export function AdminPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague, season } = useLeague();

  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);

  useEffect(() => {
    if (validId && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, leagueId, selectedLeague?.league_id, selectLeague]);

  if (!validId) {
    return <Navigate to="/" replace />;
  }

  const leagueName = membership?.name ?? `League ${leagueId}`;

  return (
    <div className="pt-5 md:pt-6">
      <h1 className="text-xl font-bold md:text-2xl">League admin</h1>
      <p className="mt-1 text-[13px] text-gray-500">{leagueName}</p>

      <AddSeasonSection leagueId={leagueId} />
      {season === null ? (
        <section aria-labelledby="h-cup-week" className="mt-7 w-full max-w-lg">
          <h2 id="h-cup-week" className="text-base font-bold">
            Cup week
          </h2>
          <EmptyState
            title="No season selected"
            detail="Add a season for this league before choosing a cup week."
          />
        </section>
      ) : (
        <CupWeekSection leagueId={leagueId} season={season} />
      )}
    </div>
  );
}
