import { createContext, useContext } from "react";

import type { PublicUser } from "../api/types";

export type AuthStatus = "loading" | "signed-in" | "signed-out";

export interface AuthContextValue {
  status: AuthStatus;
  user: PublicUser | null;
  /** A non-401 failure while loading the session, if any. */
  bootError: string | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, inviteCode: string) => Promise<void>;
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
