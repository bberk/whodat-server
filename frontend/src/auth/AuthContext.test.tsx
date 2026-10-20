import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/endpoints";
import {
  errorResponse,
  jsonResponse,
  memberUser,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";
import { useAuth } from "./AuthContext";
import { AuthProvider } from "./AuthProvider";

function Probe() {
  const { status, user, bootError, login, signup, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.email ?? ""}</span>
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

  it("logs in, exposes the user, and later logs out", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path.endsWith("/auth/login")) {
        expect(requestBody(init)).toEqual({
          email: "member@example.com",
          password: "password",
        });
        return jsonResponse(memberUser);
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

  it("signs up with the invite code and exposes the new user", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (requestPath(url).endsWith("/auth/signup")) {
        expect(requestBody(init)).toEqual({
          email: "new@example.com",
          password: "password",
          invite_code: "invite-code",
        });
        return jsonResponse({ id: 3, email: "new@example.com", role: "member" }, { status: 201 });
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
  });
});
