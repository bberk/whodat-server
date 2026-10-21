import { createContext, useContext } from "react";

import type { MeResponse } from "../api/types";

export type AuthStatus = "loading" | "signed-in" | "signed-out";

export interface AuthContextValue {
  status: AuthStatus;
  /** The `GET /me` shape, including `has_league`, which gates onboarding. */
  user: MeResponse | null;
  /** A non-401 failure while loading the session, if any. */
  bootError: string | null;
  /** Log in, then replace the partial login payload with a fresh `GET /me`. */
  login: (email: string, password: string) => Promise<MeResponse>;
  /** Sign up, then replace the signup payload with a fresh `GET /me`. */
  signup: (email: string, password: string, inviteCode: string) => Promise<MeResponse>;
  /** Re-read `GET /me` after onboarding so `has_league` reflects the new membership. */
  refreshUser: () => Promise<MeResponse>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

/** Read the auth state. Throws when called outside {@link AuthProvider}. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
