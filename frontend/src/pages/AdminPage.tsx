import { useEffect } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { DeleteLeagueSection } from "../leagues/DeleteLeagueSection";
import { EloSettingsSection } from "../leagues/EloSettingsSection";
import { InvitesSection } from "../leagues/InvitesSection";
import { useLeague } from "../leagues/LeagueContext";
import { MembersSection } from "../leagues/MembersSection";
import { SeasonsSection } from "../leagues/SeasonsSection";

/**
 * League administration page (AC-FE-13/14/15/16).
 *
 * The route is wrapped in the admin guard, so non-admins are redirected before this page renders.
 * The page hosts member management, the single seasons table (add, cup week, refresh, and delete
 * per season), invite generation, and league deletion. Simulation controls live on the standings
 * page. The shell hides its season picker on this route; the seasons table is the only refresh
 * mechanism in the UI. Each section owns its forms, validation, loading/error/success states, and
 * confirmations.
 */
export function AdminPage() {
  const params = useParams();
  const leagueId = Number(params.leagueId);
  const validId = Number.isInteger(leagueId) && leagueId > 0;
  const { leagues, selectedLeague, selectLeague, reloadLeagues } = useLeague();
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
      <p className="mt-1 text-[13px] text-ink-faint">{leagueName}</p>

      <MembersSection leagueId={leagueId} onSelfRemoved={leaveAfterRemoval} />

      <SeasonsSection leagueId={leagueId} />

      <EloSettingsSection leagueId={leagueId} />

      <InvitesSection leagueId={leagueId} />

      <DeleteLeagueSection
        leagueId={leagueId}
        leagueName={leagueName}
        onDeleted={leaveAfterRemoval}
      />
    </div>
  );
}
