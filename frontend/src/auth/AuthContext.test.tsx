import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/endpoints";
import {
  adminWithoutLeague,
  errorResponse,
  jsonResponse,
  memberUser,
  mockFetch,
  requestBody,
  requestPath,
  signupLeague,
} from "../test/fixtures";
import { useAuth } from "./AuthContext";
import { AuthProvider } from "./AuthProvider";

function Probe() {
  const { status, user, bootError, login, signup, refreshUser, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.email ?? ""}</span>
      <span data-testid="has-league">{String(user?.has_league ?? "")}</span>
      <span data-testid="boot-error">{bootError ?? ""}</span>
      <button type="button" onClick={() => void login("member@example.com", "password")}>
        login
      </button>
      <button
        type="button"
        onClick={() => void signup("new@example.com", "password", "invite-code")}
      >
        signup
      </button>
      <button type="button" onClick={() => void refreshUser()}>
        refresh
      </button>
      <button type="button" onClick={() => void logout()}>
        logout
      </button>
      <button type="button" onClick={() => void api.myLeagues().catch(() => undefined)}>
        load leagues
      </button>
    </div>
  );
}

function renderAuth() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthProvider", () => {
  it("loads the current user from GET /me", async () => {
    mockFetch(() => jsonResponse(memberUser));
    renderAuth();
    expect(screen.getByTestId("status")).toHaveTextContent("loading");
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("member@example.com");
    expect(screen.getByTestId("has-league")).toHaveTextContent("true");
  });

  it("treats a 401 from GET /me as signed out", async () => {
    mockFetch(() =>
      errorResponse(401, { code: "not_authenticated", message: "Authentication required" }),
    );
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("boot-error")).toHaveTextContent("");
  });

  it("logs in through a fresh GET /me before exposing the user", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/login") {
        expect(requestBody(init)).toEqual({
          email: "member@example.com",
          password: "password",
        });
        signedIn = true;
        // The login payload carries no has_league; the provider must refetch /me.
        return jsonResponse({ id: 2, email: "member@example.com", role: "member" });
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse(memberUser)
          : errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
      }
      if (path.endsWith("/auth/logout")) {
        return jsonResponse({ status: "ok" });
      }
      return errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
    });
    renderAuth();
    await screen.findByText("signed-out");
    await user.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("member@example.com");
    expect(screen.getByTestId("has-league")).toHaveTextContent("true");
    expect(
      fetchMock.mock.calls
        .map(([url]) => requestPath(String(url)))
        .filter((path) => path === "/api/v1/me"),
    ).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "logout" }));
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });
  });

  it("clears the session when a later API call returns 401", async () => {
    const user = userEvent.setup();
    mockFetch((url) => {
      if (requestPath(url) === "/api/v1/me") {
        return jsonResponse(memberUser);
      }
      return errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
    });
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("member@example.com");

    await user.click(screen.getByRole("button", { name: "load leagues" }));

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("");
  });

  it("signs up with a member invite, then reads the league from a fresh GET /me", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/signup") {
        expect(requestBody(init)).toEqual({
          email: "new@example.com",
          password: "password",
          invite_code: "invite-code",
        });
        signedIn = true;
        return jsonResponse(
          { id: 3, email: "new@example.com", role: "member", league: signupLeague },
          { status: 201 },
        );
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse({ ...memberUser, id: 3, email: "new@example.com", has_league: true })
          : errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
      }
      return errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
    });
    renderAuth();
    await screen.findByText("signed-out");
    await user.click(screen.getByRole("button", { name: "signup" }));
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("new@example.com");
    expect(screen.getByTestId("has-league")).toHaveTextContent("true");
    expect(
      fetchMock.mock.calls
        .map(([url]) => requestPath(String(url)))
        .filter((path) => path === "/api/v1/me"),
    ).toHaveLength(2);
  });

  it("keeps an admin invite account league-less after signup", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/signup") {
        signedIn = true;
        return jsonResponse(
          { id: 3, email: "new@example.com", role: "admin", league: null },
          { status: 201 },
        );
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse(adminWithoutLeague)
          : errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
      }
      return errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
    });
    renderAuth();
    await screen.findByText("signed-out");
    await user.click(screen.getByRole("button", { name: "signup" }));
    await waitFor(() => {
      expect(screen.getByTestId("has-league")).toHaveTextContent("false");
    });
  });

  it("refreshUser re-reads /me so onboarding can open the gate", async () => {
    const user = userEvent.setup();
    let hasLeague = false;
    mockFetch((url) => {
      if (requestPath(url) === "/api/v1/me") {
        return jsonResponse({ ...adminWithoutLeague, has_league: hasLeague });
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });
    renderAuth();
    await waitFor(() => {
      expect(screen.getByTestId("has-league")).toHaveTextContent("false");
    });

    hasLeague = true;
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() => {
      expect(screen.getByTestId("has-league")).toHaveTextContent("true");
    });
  });
});
