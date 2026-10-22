import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { LoadingState } from "../components/DataStates";
import { useAuth } from "./AuthContext";

function SessionLoading() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-10 md:px-6">
      <LoadingState label="Checking your session…" />
    </div>
  );
}

/**
 * Route guard for signed-in pages. While the session loads it shows a loading state; a visitor
 * without a session is sent to `/login` with the requested location in router state so the login
 * page can return them there (AC-FE-08).
 *
 * A signed-in account with no league is sent to mandatory onboarding, so no standings route is
 * reachable before the account owns a league (AC-AU-14).
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return <SessionLoading />;
  }
  if (status === "signed-out") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (user !== null && !user.has_league) {
    return <Navigate to="/onboarding" replace />;
  }
  return <>{children}</>;
}

/**
 * Route guard for admin-only pages. It runs inside {@link ProtectedRoute}, so the session is
 * already resolved; a signed-in non-admin is sent to the standings (AC-FE-11).
 */
export function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  if (user === null || user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

/**
 * Route guard for the onboarding page. It needs a session but not a league.
 *
 * An account that already holds a league is sent to the standings instead, so onboarding cannot be
 * replayed to add a league by that route (AC-AU-14).
 */
export function OnboardingRoute({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return <SessionLoading />;
  }
  if (status === "signed-out") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (user !== null && user.has_league) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
