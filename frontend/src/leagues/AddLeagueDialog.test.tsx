import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import type { LeagueContextValue } from "./LeagueContext";
import { LeagueContext } from "./LeagueContext";
import { AddLeagueDialog } from "./AddLeagueDialog";
import {
  adminUser,
  errorResponse,
  jsonResponse,
  leagueAlpha,
  leagueBeta,
  memberUser,
  mockFetch,
  requestBody,
  requestPath,
} from "../test/fixtures";

function authValue(user = adminUser): AuthContextValue {
  return {
    status: "signed-in",
    user,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn(),
    logout: vi.fn(),
  };
}

function leagueValue(overrides: Partial<LeagueContextValue> = {}): LeagueContextValue {
  return {
    leagues: [leagueAlpha],
    leaguesStatus: "ready",
    leaguesError: null,
    selectedLeague: leagueAlpha,
    selectLeague: vi.fn(),
    seasons: [2026],
    seasonsStatus: "ready",
    seasonsError: null,
    season: 2026,
    selectSeason: vi.fn(),
    upsertLeague: vi.fn(),
    reloadLeagues: vi.fn(),
    dataVersion: 0,
    notifyDataChanged: vi.fn(),
    ...overrides,
  };
}

function renderDialog(
  options: { user?: typeof adminUser; league?: LeagueContextValue; onClose?: () => void } = {},
) {
  const onClose = options.onClose ?? vi.fn();
  const view = render(
    <AuthContext.Provider value={authValue(options.user ?? adminUser)}>
      <LeagueContext.Provider value={options.league ?? leagueValue()}>
        <AddLeagueDialog open onClose={onClose} />
      </LeagueContext.Provider>
    </AuthContext.Provider>,
  );
  return { onClose, unmount: view.unmount };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

/** [status, code, message, retryAfter] for the member redeem failure cases. */
const redeemFailures: Array<[number, string, string, number | null]> = [
  [400, "invalid_invite", "Invite code is invalid or expired", null],
  [409, "already_member", "You already belong to this league", null],
  [429, "rate_limited", "Too many requests", 12],
];

describe("AddLeagueDialog", () => {
  it("shows credential fields only to admins", () => {
    const admin = renderDialog();
    expect(screen.getByLabelText("ESPN_S2")).toBeInTheDocument();
    expect(screen.getByLabelText("ESPN_SWID")).toBeInTheDocument();
    admin.unmount();

    renderDialog({ user: memberUser });
    expect(screen.queryByLabelText("ESPN_S2")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("ESPN_SWID")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("ESPN league id")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Invite code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join league" })).toBeInTheDocument();
  });

  it("requires an ESPN league id before calling the API", async () => {
    const fetchMock = mockFetch(() => jsonResponse({}));
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Add league" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an ESPN league id.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires both ESPN cookies or neither", async () => {
    const fetchMock = mockFetch(() => jsonResponse({}));
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByLabelText("ESPN league id"), "333");
    await user.type(screen.getByLabelText("ESPN_S2"), "only-one");
    await user.click(screen.getByRole("button", { name: "Add league" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter both ESPN_S2 and ESPN_SWID");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("joins with an invite code as a member and selects the returned league", async () => {
    const user = userEvent.setup();
    const league = leagueValue();
    const { onClose } = renderDialog({ user: memberUser, league });
    const joined = { ...leagueBeta, name: "Beta League" };
    const fetchMock = mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/me/leagues/redeem-invite" && init.method === "POST") {
        expect(requestBody(init)).toEqual({ invite_code: "member-code" });
        return jsonResponse({ league: joined }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });

    await user.type(screen.getByLabelText("Invite code"), "member-code");
    await user.click(screen.getByRole("button", { name: "Join league" }));

    await waitFor(() => {
      expect(league.upsertLeague).toHaveBeenCalledWith(joined);
    });
    expect(league.notifyDataChanged).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("requires an invite code before calling redeem", async () => {
    const fetchMock = mockFetch(() => jsonResponse({}));
    const user = userEvent.setup();
    renderDialog({ user: memberUser });
    await user.click(screen.getByRole("button", { name: "Join league" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an invite code.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(redeemFailures)(
    "shows the redeem %i response and keeps the member form usable",
    async (status, code, message, retryAfter) => {
      const user = userEvent.setup();
      const league = leagueValue();
      const { onClose } = renderDialog({ user: memberUser, league });
      mockFetch(() => errorResponse(status, { code, message }, retryAfter ?? undefined));

      await user.type(screen.getByLabelText("Invite code"), "member-code");
      await user.click(screen.getByRole("button", { name: "Join league" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(message);
      if (retryAfter === null) {
        expect(alert).not.toHaveTextContent("Try again in");
      } else {
        expect(alert).toHaveTextContent(`Try again in ${retryAfter} seconds`);
      }
      // The submitted code is never echoed, the dialog stays open, and the form can be retried.
      expect(alert).not.toHaveTextContent("member-code");
      expect(screen.getByLabelText("Invite code")).toHaveValue("member-code");
      expect(screen.getByRole("button", { name: "Join league" })).toBeEnabled();
      expect(league.upsertLeague).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    },
  );

  it("posts the league with optional season and credentials, then selects it", async () => {
    const user = userEvent.setup();
    const league = leagueValue();
    const { onClose } = renderDialog({ league });
    const added = { ...leagueAlpha, league_id: 3, name: "Gamma League", external_id: "333" };
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues" && init.method === "POST") {
        expect(requestBody(init)).toEqual({
          espn_league_id: "333",
          season: 2026,
          espn_s2: "s2-value",
          espn_swid: "swid-value",
        });
        return jsonResponse({ league: added, season: 2026, weeks_synced: [1, 2] }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });

    await user.type(screen.getByLabelText("ESPN league id"), "333");
    await user.type(screen.getByLabelText(/Season/), "2026");
    await user.type(screen.getByLabelText("ESPN_S2"), "s2-value");
    await user.type(screen.getByLabelText("ESPN_SWID"), "swid-value");
    await user.click(screen.getByRole("button", { name: "Add league" }));

    await waitFor(() => {
      expect(league.upsertLeague).toHaveBeenCalledWith(added);
    });
    expect(league.notifyDataChanged).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("validates the season and shows an API error from the add request", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() =>
      errorResponse(409, { code: "already_member", message: "You already belong to this league" }),
    );
    renderDialog();
    await user.type(screen.getByLabelText("ESPN league id"), "333");
    await user.type(screen.getByLabelText(/Season/), "1990");
    await user.click(screen.getByRole("button", { name: "Add league" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Season must be a whole year between");
    expect(fetchMock).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText(/Season/));
    await user.click(screen.getByRole("button", { name: "Add league" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already belong to this league");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
