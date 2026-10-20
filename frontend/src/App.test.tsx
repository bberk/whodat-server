import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "./App";
import {
  adminUser,
  errorResponse,
  historyResponse,
  jsonResponse,
  leagueAlpha,
  leagueBeta,
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
});
