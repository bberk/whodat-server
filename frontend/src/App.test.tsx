import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App, AppRoutes } from "./App";
import {
  adminUser,
  adminWithoutLeague,
  errorResponse,
  historyResponse,
  jsonResponse,
  leagueAlpha,
  leagueBeta,
  memberUser,
  mockFetch,
  owners,
  requestBody,
  requestPath,
  standingsResponse,
} from "./test/fixtures";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function signedInFetch(options: { seasonsAlpha?: number[]; seasonsBeta?: number[] } = {}) {
  const seasonsAlpha = options.seasonsAlpha ?? [2024, 2026];
  const seasonsBeta = options.seasonsBeta ?? [2025];
  return mockFetch((url, init) => {
    const path = requestPath(url);
    if (path === "/api/v1/me") {
      return jsonResponse(adminUser);
    }
    if (path === "/api/v1/me/leagues") {
      return jsonResponse([leagueAlpha, leagueBeta]);
    }
    if (path === "/api/v1/leagues/1/seasons") {
      return jsonResponse({ seasons: seasonsAlpha });
    }
    if (path === "/api/v1/leagues/2/seasons") {
      return jsonResponse({ seasons: seasonsBeta });
    }
    if (/^\/api\/v1\/leagues\/\d+\/seasons\/\d+\/standings$/.test(path)) {
      const [, leagueId, season] = path.match(/leagues\/(\d+)\/seasons\/(\d+)\/standings/) ?? [];
      return jsonResponse({
        ...standingsResponse,
        league_id: Number(leagueId),
        season: Number(season),
      });
    }
    if (/^\/api\/v1\/leagues\/\d+\/seasons\/\d+\/vp-history$/.test(path)) {
      return jsonResponse(historyResponse);
    }
    if (path === "/api/v1/leagues/1/owners") {
      return jsonResponse({ owners });
    }
    if (path === "/api/v1/me/leagues/1/owner") {
      expect(init?.method).toBe("PUT");
      return jsonResponse({ league: { ...leagueAlpha, owner_id: 3 } });
    }
    if (path === "/api/v1/auth/logout") {
      return jsonResponse({ status: "ok" });
    }
    return errorResponse(404, { code: "not_found", message: `Unhandled ${path}` });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

describe("App routing", () => {
  it("returns to the requested route after login", async () => {
    const user = userEvent.setup();
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/login") {
        return jsonResponse(adminUser);
      }
      if (path === "/api/v1/me") {
        return errorResponse(401, {
          code: "not_authenticated",
          message: "Authentication required",
        });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/leagues/1/owner");
    await screen.findByRole("heading", { level: 1, name: "Log in" });

    // The login succeeds, then the guard re-renders and the league shell loads its data.
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/login") {
        return jsonResponse(adminUser);
      }
      if (path === "/api/v1/me") {
        return jsonResponse(adminUser);
      }
      if (path === "/api/v1/me/leagues") {
        return jsonResponse([leagueAlpha]);
      }
      if (path === "/api/v1/leagues/1/seasons") {
        return jsonResponse({ seasons: [2026] });
      }
      if (path === "/api/v1/leagues/1/owners") {
        return jsonResponse({ owners });
      }
      if (/^\/api\/v1\/leagues\/1\/seasons\/2026\/(standings|vp-history)$/.test(path)) {
        return path.endsWith("standings")
          ? jsonResponse(standingsResponse)
          : jsonResponse(historyResponse);
      }
      return errorResponse(404, { code: "not_found", message: path });
    });

    await user.type(screen.getByLabelText("Email"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    // The league shell remounts its outlet when the selected season arrives, so wait for the
    // final season before asserting the routed page to avoid reading a soon-detached heading.
    await waitFor(() => {
      expect(screen.getByLabelText("Season")).toHaveValue("2026");
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Owner · Alpha League" }),
    ).toBeInTheDocument();
  });

  it("picks the first league and its latest season on load, then logs out", async () => {
    const user = userEvent.setup();
    const fetchMock = signedInFetch({ seasonsAlpha: [2024, 2026] });
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Alpha League — standings" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Season")).toHaveValue("2026");
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls.some((url) => url.includes("/leagues/1/seasons/2026/standings"))).toBe(true);
    expect(urls.some((url) => url.includes("/leagues/1/seasons/2024/standings"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
  });

  it("switches league and season and reloads standings", async () => {
    const user = userEvent.setup();
    const fetchMock = signedInFetch({ seasonsAlpha: [2025, 2026], seasonsBeta: [2024] });
    renderAt("/");
    await screen.findByRole("heading", { level: 1, name: "Alpha League — standings" });
    expect(screen.getByLabelText("Season")).toHaveValue("2026");

    await user.selectOptions(screen.getByLabelText("League"), "2");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Beta League — standings" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Season")).toHaveValue("2024");
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([url]) => String(url));
      expect(urls.some((url) => url.includes("/leagues/2/seasons/2024/standings"))).toBe(true);
    });
  });

  it("shows a structured login error and stays on the login page", async () => {
    const user = userEvent.setup();
    mockFetch((url) =>
      requestPath(url).endsWith("/auth/login")
        ? errorResponse(401, { code: "invalid_credentials", message: "Invalid email or password" })
        : errorResponse(401, { code: "not_authenticated", message: "Authentication required" }),
    );
    renderAt("/login");
    await screen.findByRole("heading", { level: 1, name: "Log in" });
    await user.type(screen.getByLabelText("Email"), "wrong@example.com");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
  });

  it("shows a signup 429 with the Retry-After window", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/signup") {
        expect(requestBody(init)).toMatchObject({
          email: "new@example.com",
          invite_code: "invite-code",
        });
        return errorResponse(429, { code: "rate_limited", message: "Too many requests" }, 30);
      }
      return errorResponse(401, { code: "not_authenticated", message: "Authentication required" });
    });
    renderAt("/signup");
    await screen.findByRole("heading", { level: 1, name: "Create an account" });
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.type(screen.getByLabelText("Invite code"), "invite-code");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30 seconds");
  });

  it("signs up with a member invite and lands on the league standings without onboarding", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/signup") {
        signedIn = true;
        return jsonResponse(
          { id: 2, email: "new@example.com", role: "member", league: leagueAlpha },
          { status: 201 },
        );
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse(memberUser)
          : errorResponse(401, {
              code: "not_authenticated",
              message: "Authentication required",
            });
      }
      if (path === "/api/v1/me/leagues") {
        return jsonResponse([leagueAlpha]);
      }
      if (path === "/api/v1/leagues/1/seasons") {
        return jsonResponse({ seasons: [2026] });
      }
      if (/^\/api\/v1\/leagues\/1\/seasons\/2026\/(standings|vp-history)$/.test(path)) {
        return path.endsWith("standings")
          ? jsonResponse(standingsResponse)
          : jsonResponse(historyResponse);
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/signup");
    await screen.findByRole("heading", { level: 1, name: "Create an account" });
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.type(screen.getByLabelText("Invite code"), "invite-code");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    // AC-AU-15: a member invite already carries the membership, so no onboarding step appears.
    expect(
      await screen.findByRole("heading", { level: 1, name: "Alpha League — standings" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).not.toBeInTheDocument();
  });

  it("forces onboarding and hides standings for an account without a league", async () => {
    const fetchMock = mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/me") {
        return jsonResponse(adminWithoutLeague);
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: /standings/i })).not.toBeInTheDocument();
    const paths = fetchMock.mock.calls.map(([url]) => requestPath(String(url)));
    expect(paths).not.toContain("/api/v1/me/leagues");
  });

  it("redirects every protected route to onboarding while the account has no league", async () => {
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/me") {
        return jsonResponse(adminWithoutLeague);
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/leagues/1/owner");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).toBeInTheDocument();
  });

  it("sends a league-bound account away from the onboarding route", async () => {
    signedInFetch();
    renderAt("/onboarding");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Alpha League — standings" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).not.toBeInTheDocument();
  });

  it("signs up with an admin invite and is forced to onboarding", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    const fetchMock = mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/signup") {
        signedIn = true;
        return jsonResponse(
          { id: 3, email: "new-admin@example.com", role: "admin", league: null },
          { status: 201 },
        );
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse(adminWithoutLeague)
          : errorResponse(401, {
              code: "not_authenticated",
              message: "Authentication required",
            });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/signup");
    await screen.findByRole("heading", { level: 1, name: "Create an account" });
    await user.type(screen.getByLabelText("Email"), "new-admin@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.type(screen.getByLabelText("Invite code"), "admin-invite");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    // AC-AU-14: the admin invite is league-less, so signup lands on onboarding, not standings.
    expect(
      await screen.findByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).toBeInTheDocument();
    const paths = fetchMock.mock.calls.map(([url]) => requestPath(String(url)));
    expect(paths).not.toContain("/api/v1/me/leagues");
  });

  it("sends an account without a league to onboarding after login", async () => {
    const user = userEvent.setup();
    let signedIn = false;
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/auth/login") {
        signedIn = true;
        return jsonResponse({ id: 3, email: "new-admin@example.com", role: "admin" });
      }
      if (path === "/api/v1/me") {
        return signedIn
          ? jsonResponse(adminWithoutLeague)
          : errorResponse(401, {
              code: "not_authenticated",
              message: "Authentication required",
            });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderAt("/login");
    await screen.findByRole("heading", { level: 1, name: "Log in" });
    await user.type(screen.getByLabelText("Email"), "new-admin@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Add your ESPN league" }),
    ).toBeInTheDocument();
  });

  it("redirects a signed-in visitor away from signup", async () => {
    signedInFetch();
    renderAt("/signup");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Alpha League — standings" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Create an account" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the owner route when a league is switched and opens the add-league dialog", async () => {
    const user = userEvent.setup();
    signedInFetch();
    renderAt("/leagues/1/owner");
    await screen.findByRole("heading", { level: 1, name: "Owner · Alpha League" });

    await user.selectOptions(screen.getByLabelText("League"), "2");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Owner · Beta League" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add league" }));
    expect(screen.getByRole("dialog", { name: "Add a league" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close add-league dialog" }));
    expect(screen.queryByRole("dialog", { name: "Add a league" })).not.toBeInTheDocument();
  });

  it("renders the browser router entrypoint", async () => {
    mockFetch(() =>
      errorResponse(401, { code: "not_authenticated", message: "Authentication required" }),
    );
    window.history.pushState({}, "", "/login");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
  });

  it("shows a boot failure on the login page", async () => {
    mockFetch(() => errorResponse(500, { code: "boom", message: "The API is unavailable." }));
    renderAt("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unavailable.");
  });

  it("shows a membership error banner without losing the shell", async () => {
    mockFetch((url) => {
      const path = requestPath(url);
      if (path === "/api/v1/me") {
        return jsonResponse(adminUser);
      }
      return errorResponse(500, { code: "boom", message: "Leagues unavailable" });
    });
    renderAt("/");
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((alert) => alert.textContent?.includes("Leagues unavailable"))).toBe(true);
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
  });
});
