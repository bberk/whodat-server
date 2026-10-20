import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { secondaryButtonClass } from "../components/formStyles";
import { AddLeagueDialog } from "../leagues/AddLeagueDialog";
import { useLeague } from "../leagues/LeagueContext";
import { LeagueSwitcher } from "../leagues/LeagueSwitcher";
import { RefreshButton } from "../leagues/RefreshButton";
import { SeasonPicker } from "../leagues/SeasonPicker";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-2.5 py-1.5 text-[13px] font-semibold ${
    isActive ? "bg-brand-foreground text-brand" : "text-gray-600 hover:text-brand"
  }`;

/** Signed-in layout: brand and navigation, league/season controls, and the routed page content. */
export function AppShell() {
  const { user, logout } = useAuth();
  const {
    leaguesStatus,
    leaguesError,
    reloadLeagues,
    selectedLeague,
    season,
    dataVersion,
    notifyDataChanged,
  } = useLeague();
  const [addOpen, setAddOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const ownerPath = selectedLeague === null ? null : `/leagues/${selectedLeague.league_id}/owner`;

  return (
    <div className="flex min-h-full flex-col bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-[1200px] px-4 md:px-6">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
            <Link to="/" className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex h-[34px] w-[34px] items-center justify-center rounded-lg bg-brand text-[15px] font-bold tracking-wide text-brand-foreground"
              >
                VP
              </span>
              <span className="text-[15px] font-semibold">Victory Points Standings</span>
            </Link>

            <div className="flex-1" />

            <nav aria-label="Primary" className="flex items-center gap-1">
              <NavLink to="/" end className={navLinkClass}>
                Standings
              </NavLink>
              {ownerPath === null ? (
                <span className="px-2.5 py-1.5 text-[13px] text-gray-400">Owner</span>
              ) : (
                <NavLink to={ownerPath} className={navLinkClass}>
                  Owner
                </NavLink>
              )}
            </nav>

            <div className="flex items-center gap-2 border-l border-gray-200 pl-3 text-[13px] text-gray-700">
              <span className="hidden max-w-[180px] truncate sm:inline">{user?.email}</span>
              <button
                type="button"
                onClick={() => {
                  void logout();
                  navigate("/login", { replace: true });
                }}
                className={secondaryButtonClass}
              >
                Log out
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-gray-100 py-2.5">
            <LeagueSwitcher
              onSelect={(leagueId) => {
                if (location.pathname.endsWith("/owner")) {
                  navigate(`/leagues/${leagueId}/owner`);
                }
              }}
            />
            <SeasonPicker />
            <RefreshButton
              leagueId={selectedLeague?.league_id ?? null}
              hasCredentials={selectedLeague?.has_credentials ?? false}
              onRefreshed={notifyDataChanged}
            />
            <div className="flex-1" />
            <button type="button" onClick={() => setAddOpen(true)} className={secondaryButtonClass}>
              Add league
            </button>
          </div>
        </div>
      </header>

      {leaguesStatus === "error" ? (
        <div
          role="alert"
          className="border-b border-red-200 bg-red-50 px-4 py-2 text-[13px] text-red-800 md:px-6"
        >
          <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-2">
            <span>{leaguesError ?? "Could not load your leagues."}</span>
            <button type="button" onClick={reloadLeagues} className={secondaryButtonClass}>
              Retry
            </button>
          </div>
        </div>
      ) : null}

      <main
        key={`${selectedLeague?.league_id ?? "none"}-${season ?? "none"}-${dataVersion}`}
        className="mx-auto w-full min-w-0 max-w-[1200px] flex-1 px-4 pb-10 md:px-6"
      >
        <Outlet />
      </main>

      <AddLeagueDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
