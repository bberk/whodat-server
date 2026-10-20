import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { LoadingState } from "../components/DataStates";
import { useAuth } from "./AuthContext";

/**
 * Route guard for signed-in pages. While the session loads it shows a loading state; a visitor
 * without a session is sent to `/login` with the requested location in router state so the login
 * page can return them there (AC-FE-08).
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 py-10 md:px-6">
        <LoadingState label="Checking your session…" />
      </div>
    );
  }
  if (status === "signed-out") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}
