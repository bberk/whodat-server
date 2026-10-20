import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/endpoints";
import { isUnauthorized } from "../api/client";
import type { PublicUser } from "../api/types";
import { AuthContext, type AuthStatus } from "./AuthContext";

interface AuthState {
  status: AuthStatus;
  user: PublicUser | null;
  bootError: string | null;
}

const SIGNED_OUT: AuthState = { status: "signed-out", user: null, bootError: null };

/**
 * Load `GET /me` once, then expose login, signup, and logout.
 *
 * A 401 from `/me` (or from any auth action) means signed out rather than an error, so an expired
 * cookie lands the visitor on the login page. Other boot failures keep the visitor signed out and
 * surface a message on the login page.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", user: null, bootError: null });

  useEffect(() => {
    const controller = new AbortController();
    api.me(controller.signal).then(
      (user) => {
        setState({ status: "signed-in", user, bootError: null });
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "signed-out",
          user: null,
          bootError: isUnauthorized(error) ? null : error instanceof Error ? error.message : null,
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const user = await api.login({ email, password });
    setState({ status: "signed-in", user, bootError: null });
  }, []);

  const signup = useCallback(async (email: string, password: string, inviteCode: string) => {
    const user = await api.signup({ email, password, invite_code: inviteCode });
    setState({ status: "signed-in", user, bootError: null });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Clearing local state is the important part; a failed logout must not trap the visitor.
    } finally {
      setState(SIGNED_OUT);
    }
  }, []);

  const value = useMemo(
    () => ({
      status: state.status,
      user: state.user,
      bootError: state.bootError,
      login,
      signup,
      logout,
    }),
    [state, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
