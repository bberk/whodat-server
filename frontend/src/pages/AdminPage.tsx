import { useEffect } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { EmptyState } from "../components/DataStates";
import { AddSeasonSection } from "../leagues/AddSeasonSection";
import { DeleteLeagueSection } from "../leagues/DeleteLeagueSection";
import { InvitesSection } from "../leagues/InvitesSection";
import { useLeague } from "../leagues/LeagueContext";
import { MembersSection } from "../leagues/MembersSection";
import { CupWeekSection } from "./CupWeekSection";

/**
 * League administration page (AC-FE-10 season add, AC-FE-11 cup week, AC-FE-13/14/15).
 *
 * The route is wrapped in the admin guard, so non-admins are redirected before this page renders.
 * The page hosts member management, adding a stored season, choosing the season's cup week,
 * generating invites, and deleting the league. The shell hides its season picker on this route,
 * so the heading names the season the cup-week section applies to. Each section owns its form,
 * validation, loading/error/success states, and confirmations.
 */
export function AdminPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague, season, reloadLeagues } = useLeague();
  const navigate = useNavigate();

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
  const leaveAfterRemoval = () => {
    reloadLeagues();
    navigate("/", { replace: true });
  };

  return (
    <div className="pt-5 md:pt-6">
      <h1 className="text-xl font-bold md:text-2xl">League admin</h1>
      <p className="mt-1 text-[13px] text-gray-500">
        {leagueName}
        {season === null ? "" : ` · ${season} season`}
      </p>

      <MembersSection leagueId={leagueId} onSelfRemoved={leaveAfterRemoval} />

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

      <InvitesSection leagueId={leagueId} />

      <DeleteLeagueSection
        leagueId={leagueId}
        leagueName={leagueName}
        onDeleted={leaveAfterRemoval}
      />
    </div>
  );
}
