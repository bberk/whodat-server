import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { LoginPage } from "./auth/LoginPage";
import { OnboardingRoute, ProtectedRoute } from "./auth/ProtectedRoute";
import { SignupPage } from "./auth/SignupPage";
import { AppShell } from "./components/AppShell";
import { LeagueProvider } from "./leagues/LeagueProvider";
import { OnboardingPage } from "./pages/OnboardingPage";
import { OwnerPage } from "./pages/OwnerPage";
import { StandingsPage } from "./pages/StandingsPage";

/** Route tree without a router, so tests can mount it inside a MemoryRouter. */
export function AppRoutes() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route
          path="/onboarding"
          element={
            <OnboardingRoute>
              <OnboardingPage />
            </OnboardingRoute>
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <LeagueProvider>
                <AppShell />
              </LeagueProvider>
            </ProtectedRoute>
          }
        >
          <Route index element={<StandingsPage />} />
          <Route path="leagues/:leagueId/owner" element={<OwnerPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
