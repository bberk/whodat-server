import { useLeague } from "./LeagueContext";
import { selectClass } from "../components/formStyles";

/** Choose one of the caller's leagues. The option text exposes whether credentials are stored. */
export function LeagueSwitcher({ onSelect }: { onSelect?: (leagueId: number) => void }) {
  const { leagues, leaguesStatus, selectedLeague, selectLeague } = useLeague();

  return (
    <div className="flex min-w-0 items-center gap-2">
      <label htmlFor="league-switcher" className="text-[13px] font-semibold text-gray-700">
        League
      </label>
      <select
        id="league-switcher"
        className={`${selectClass} max-w-[220px]`}
        value={selectedLeague?.league_id ?? ""}
        onChange={(event) => {
          const leagueId = Number(event.target.value);
          selectLeague(leagueId);
          onSelect?.(leagueId);
        }}
        disabled={leaguesStatus !== "ready" || leagues.length === 0}
        aria-label="League"
      >
        {leaguesStatus === "loading" ? <option value="">Loading leagues…</option> : null}
        {leaguesStatus === "ready" && leagues.length === 0 ? (
          <option value="">No leagues yet</option>
        ) : null}
        {leagues.map((league) => (
          <option key={league.league_id} value={league.league_id}>
            {league.name} — {league.has_credentials ? "credentials" : "no credentials"}
          </option>
        ))}
      </select>
    </div>
  );
}
