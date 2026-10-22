import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { AddSeasonSection } from "../leagues/AddSeasonSection";
import { useLeague } from "../leagues/LeagueContext";

/**
 * League administration page (AC-FE-10).
 *
 * The page is reachable only inside the protected shell. The admin controls render only for a
 * global admin; the API still enforces the role and membership server-side. The add-season section
 * owns its own form, validation, and success/error states.
 */
export function AdminPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { user } = useAuth();
  const { leagues, selectedLeague, selectLeague } = useLeague();
  const isAdmin = user?.role === "admin";

  const membership =
    leagues.find((league) => league.league_id === leagueId) ??
    (selectedLeague?.league_id === leagueId ? selectedLeague : null);

  useEffect(() => {
    if (validId && isAdmin && selectedLeague?.league_id !== leagueId) {
      selectLeague(leagueId);
    }
  }, [validId, isAdmin, leagueId, selectedLeague?.league_id, selectLeague]);

  const leagueName = membership?.name ?? `League ${validId ? leagueId : ""}`;

  return (
    <div className="pt-5 md:pt-6">
      <h1 className="text-xl font-bold md:text-2xl">League admin</h1>
      <p className="mt-1 text-[13px] text-gray-500">{leagueName}</p>

      {isAdmin ? null : (
        <p role="alert" className="mt-4 max-w-lg text-[13px] text-red-800">
          Only league admins can manage this league.
        </p>
      )}
      {isAdmin && !validId ? (
        <p role="alert" className="mt-4 max-w-lg text-[13px] text-red-800">
          This league id is not valid.
        </p>
      ) : null}
      {isAdmin && validId ? <AddSeasonSection leagueId={leagueId} /> : null}
    </div>
  );
}
