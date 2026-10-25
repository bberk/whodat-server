import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { secondaryButtonClass } from "../components/formStyles";
import { AddLeagueDialog } from "../leagues/AddLeagueDialog";
import { useLeague } from "../leagues/LeagueContext";
import { LeagueSwitcher } from "../leagues/LeagueSwitcher";
import { SeasonPicker } from "../leagues/SeasonPicker";
import { ThemeToggle } from "../theme/ThemeToggle";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-2.5 py-1.5 text-[13px] font-semibold ${
    isActive ? "bg-brand-soft text-brand-ink" : "text-ink-subtle hover:text-brand-ink"
  }`;

/** Signed-in layout: brand and navigation, league/season controls, theme control, and the page. */
export function AppShell() {
  const { user, logout } = useAuth();
  const { leaguesStatus, leaguesError, reloadLeagues, selectedLeague, season } = useLeague();
  const [addOpen, setAddOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const ownerPath = selectedLeague === null ? null : `/leagues/${selectedLeague.league_id}/owner`;
  const historyPath =
    selectedLeague === null ? null : `/leagues/${selectedLeague.league_id}/history`;
  const adminPath = selectedLeague === null ? null : `/leagues/${selectedLeague.league_id}/admin`;
  // The owner, history, and admin pages each own their context; only standings uses the season picker.
  const showSeasonPicker =
    !location.pathname.endsWith("/owner") &&
    !location.pathname.endsWith("/history") &&
    !location.pathname.endsWith("/admin");

  return (
    <div className="flex min-h-full flex-col bg-page text-ink">
      <header className="border-b border-line bg-surface">
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
              {historyPath === null ? (
                <span className="px-2.5 py-1.5 text-[13px] text-ink-faint">History</span>
              ) : (
                <NavLink to={historyPath} className={navLinkClass}>
                  History
                </NavLink>
              )}
              {ownerPath === null ? (
                <span className="px-2.5 py-1.5 text-[13px] text-ink-faint">Owner</span>
              ) : (
                <NavLink to={ownerPath} className={navLinkClass}>
                  Owner
                </NavLink>
              )}
              {adminPath === null || user?.role !== "admin" ? null : (
                <NavLink to={adminPath} className={navLinkClass}>
                  Admin
                </NavLink>
              )}
            </nav>

            <div className="flex items-center gap-2 border-l border-line pl-3 text-[13px] text-ink-muted">
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

          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line-subtle py-2.5">
            <LeagueSwitcher
              onSelect={(leagueId) => {
                const suffix = location.pathname.endsWith("/owner")
                  ? "/owner"
                  : location.pathname.endsWith("/history")
                    ? "/history"
                    : location.pathname.endsWith("/admin")
                      ? "/admin"
                      : null;
                if (suffix !== null) {
                  navigate(`/leagues/${leagueId}${suffix}`);
                }
              }}
            />
            {showSeasonPicker ? <SeasonPicker /> : null}
            <div className="flex-1" />
            <ThemeToggle />
            <button type="button" onClick={() => setAddOpen(true)} className={secondaryButtonClass}>
              {user?.role === "admin" ? "Add league" : "Join league"}
            </button>
          </div>
        </div>
      </header>

      {leaguesStatus === "error" ? (
        <div
          role="alert"
          className="border-b border-danger-line bg-danger-surface px-4 py-2 text-[13px] text-danger-ink md:px-6"
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
        key={`${selectedLeague?.league_id ?? "none"}-${season ?? "none"}`}
        className="mx-auto w-full min-w-0 max-w-[1200px] flex-1 px-4 pb-10 md:px-6"
      >
        <Outlet />
      </main>

      <AddLeagueDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
