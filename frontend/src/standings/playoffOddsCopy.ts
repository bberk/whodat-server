import type { PlayoffOddsUnavailableReason } from "./usePlayoffOdds";

/** Reason-specific copy shared by the standings section and the admin simulation runner. */
export const PLAYOFF_ODDS_UNAVAILABLE_COPY: Record<
  PlayoffOddsUnavailableReason,
  { title: string; detail: string }
> = {
  no_completed_weeks: {
    title: "No completed weeks yet",
    detail: "Playoff odds appear after the first completed week of the season.",
  },
  missing_playoff_field: {
    title: "Playoff settings are incomplete",
    detail:
      "This season's stored playoff field size is missing or too small for its divisions. An admin can re-sync the season.",
  },
  incomplete_schedule: {
    title: "Remaining schedule is incomplete",
    detail:
      "The rest of the season is not fully stored, so odds cannot be simulated. An admin can re-sync this season.",
  },
  unsupported_division_shape: {
    title: "Division setup is not supported",
    detail:
      "Every team needs a stored division before playoff seeding can be estimated. An admin can re-sync this season.",
  },
};
