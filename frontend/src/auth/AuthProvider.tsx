import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/endpoints";
import { isUnauthorized, onUnauthorized } from "../api/client";
import type { MeResponse } from "../api/types";
import { AuthContext, type AuthStatus } from "./AuthContext";

interface AuthState {
  status: AuthStatus;
  user: MeResponse | null;
  bootError: string | null;
}

const SIGNED_OUT: AuthState = { status: "signed-out", user: null, bootError: null };

/**
 * Load `GET /me` once, then expose login, signup, refresh, and logout.
 *
 * A 401 from `/me` (or from any auth action) means signed out rather than an error, so an expired
 * cookie lands the visitor on the login page. A 401 from any later API call while signed in also
 * clears the session, so an expired cookie cannot leave a broken signed-in shell behind. Other
 * boot failures keep the visitor signed out and surface a message on the login page.
 *
 * Login and signup responses are only partial: neither carries `has_league`. Both therefore
 * replace the response with a fresh `GET /me` before touching state, so the onboarding gate always
 * sees the server's answer rather than an optimistic guess.
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

  useEffect(
    () =>
      onUnauthorized(() => {
        setState((current) => (current.status === "signed-in" ? SIGNED_OUT : current));
      }),
    [],
  );

  const refreshUser = useCallback(async () => {
    const user = await api.me();
    setState({ status: "signed-in", user, bootError: null });
    return user;
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      await api.login({ email, password });
      return refreshUser();
    },
    [refreshUser],
  );

  const signup = useCallback(
    async (email: string, password: string, inviteCode: string) => {
      await api.signup({ email, password, invite_code: inviteCode });
      return refreshUser();
    },
    [refreshUser],
  );

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
      refreshUser,
      logout,
    }),
    [state, login, signup, refreshUser, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
