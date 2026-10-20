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

describe("AddLeagueDialog", () => {
  it("shows credential fields only to admins", () => {
    const admin = renderDialog();
    expect(screen.getByLabelText("ESPN_S2")).toBeInTheDocument();
    expect(screen.getByLabelText("ESPN_SWID")).toBeInTheDocument();
    admin.unmount();

    renderDialog({ user: memberUser });
    expect(screen.queryByLabelText("ESPN_S2")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("ESPN_SWID")).not.toBeInTheDocument();
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
});
