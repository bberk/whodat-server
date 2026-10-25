import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import {
  adminUser,
  adminWithoutLeague,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";
import { OnboardingPage } from "./OnboardingPage";
import { ThemeProvider } from "../theme/ThemeProvider";

function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: "signed-in",
    user: adminWithoutLeague,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn().mockResolvedValue(adminUser),
    logout: vi.fn(),
    ...overrides,
  };
}

function renderPage(value: AuthContextValue = authValue()) {
  return render(
    <ThemeProvider>
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={["/onboarding"]}>
          <Routes>
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/" element={<p>standings destination</p>} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>,
  );
}

async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  options: { leagueId?: string; season?: string; s2?: string; swid?: string } = {},
) {
  const leagueId = options.leagueId ?? "333";
  if (leagueId !== "") {
    await user.type(screen.getByLabelText("ESPN league id"), leagueId);
  }
  if (options.season !== undefined) {
    await user.clear(screen.getByLabelText("Season"));
    await user.type(screen.getByLabelText("Season"), options.season);
  }
  await user.type(screen.getByLabelText("ESPN_S2"), options.s2 ?? "s2-secret");
  await user.type(screen.getByLabelText("ESPN_SWID"), options.swid ?? "swid-secret");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OnboardingPage", () => {
  it("defaults the season to the current year and labels every required field", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Add your ESPN league" })).toBeVisible();
    const leagueId = screen.getByLabelText("ESPN league id");
    expect(leagueId).toBeRequired();
    expect(leagueId).toHaveAttribute("maxLength", "64");
    expect(leagueId).toHaveAttribute("pattern", "[A-Za-z0-9._-]+");
    expect(leagueId).toHaveAttribute("inputMode", "text");
    expect(screen.getByLabelText("Season")).toHaveValue(new Date().getFullYear());
    expect(screen.getByLabelText("ESPN_S2")).toBeRequired();
    expect(screen.getByLabelText("ESPN_SWID")).toBeRequired();
    expect(screen.getByText(/stored encrypted and are never shown again/i)).toBeInTheDocument();
  });

  it("validates the league id, the season, and both cookies before calling the API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => jsonResponse({}));
    renderPage();

    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your ESPN league id.");

    await user.type(screen.getByLabelText("ESPN league id"), "333");
    await user.clear(screen.getByLabelText("Season"));
    await user.type(screen.getByLabelText("Season"), "1999");
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Season must be a whole year between 2000 and 2100.",
    );

    await user.clear(screen.getByLabelText("Season"));
    await user.type(screen.getByLabelText("Season"), "2026");
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter both ESPN_S2 and ESPN_SWID.");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects non-ASCII league ids and credentials before calling the API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => jsonResponse({}));
    renderPage();

    await user.type(screen.getByLabelText("ESPN league id"), "لیگ");
    await user.type(screen.getByLabelText("ESPN_S2"), "s2-secret");
    await user.type(screen.getByLabelText("ESPN_SWID"), "swid-secret");
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "ESPN league id must contain only ASCII characters.",
    );

    await user.clear(screen.getByLabelText("ESPN league id"));
    await user.type(screen.getByLabelText("ESPN league id"), "333");
    await user.clear(screen.getByLabelText("ESPN_S2"));
    await user.type(screen.getByLabelText("ESPN_S2"), "s2🙂secret");
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "ESPN_S2 must contain only ASCII characters.",
    );

    await user.clear(screen.getByLabelText("ESPN_S2"));
    await user.type(screen.getByLabelText("ESPN_S2"), "s2-secret");
    await user.clear(screen.getByLabelText("ESPN_SWID"));
    await user.type(screen.getByLabelText("ESPN_SWID"), "swidésecret");
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "ESPN_SWID must contain only ASCII characters.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("adds the league, refreshes the session, and lands on the standings", async () => {
    const user = userEvent.setup();
    const value = authValue();
    const fetchMock = mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues" && init.method === "POST") {
        expect(requestBody(init)).toEqual({
          espn_league_id: "333",
          season: 2026,
          espn_s2: "s2-secret",
          espn_swid: "swid-secret",
        });
        return jsonResponse(
          { league: leagueAlpha, season: 2026, weeks_synced: [1] },
          { status: 201 },
        );
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });

    renderPage(value);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));

    expect(await screen.findByText("standings destination")).toBeInTheDocument();
    expect(value.refreshUser).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a 422 field error and keeps the form usable without echoing credentials", async () => {
    const user = userEvent.setup();
    const value = authValue();
    mockFetch(() =>
      errorResponse(422, [
        { loc: ["body", "espn_league_id"], msg: "Input should be a valid league id" },
      ]),
    );
    renderPage(value);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Input should be a valid league id");
    expect(alert).toHaveTextContent("espn_league_id");
    expect(document.body.textContent).not.toContain("s2-secret");
    expect(screen.getByLabelText("ESPN league id")).toHaveValue("333");
    expect(screen.getByRole("button", { name: "Add league and continue" })).toBeEnabled();
    expect(value.refreshUser).not.toHaveBeenCalled();
  });

  it("shows the 429 retry window and keeps the form usable", async () => {
    const user = userEvent.setup();
    const value = authValue();
    mockFetch(() => errorResponse(429, { code: "rate_limited", message: "Too many requests" }, 30));
    renderPage(value);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Add league and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30 seconds");
    expect(screen.getByLabelText("ESPN_S2")).toHaveValue("s2-secret");
    expect(screen.getByRole("button", { name: "Add league and continue" })).toBeEnabled();
    await waitFor(() => {
      expect(value.refreshUser).not.toHaveBeenCalled();
    });
  });
});
