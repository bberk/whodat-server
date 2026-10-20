import { selectClass } from "../components/formStyles";
import { useLeague } from "./LeagueContext";

/** Choose a stored season for the selected league; defaults to the latest season. */
export function SeasonPicker() {
  const { seasons, seasonsStatus, season, selectSeason } = useLeague();

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="season-picker" className="text-[13px] font-semibold text-gray-700">
        Season
      </label>
      <select
        id="season-picker"
        className={selectClass}
        value={season ?? ""}
        onChange={(event) => selectSeason(Number(event.target.value))}
        disabled={seasonsStatus !== "ready" || seasons.length === 0}
        aria-label="Season"
      >
        {seasonsStatus === "loading" ? <option value="">Loading seasons…</option> : null}
        {seasonsStatus === "ready" && seasons.length === 0 ? (
          <option value="">No seasons yet</option>
        ) : null}
        {seasons.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </div>
  );
}
