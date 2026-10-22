import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LeagueMemberSummary } from "../api/types";
import type { AuthContextValue } from "../auth/AuthContext";
import { AuthContext } from "../auth/AuthContext";
import {
  adminUser,
  errorResponse,
  jsonResponse,
  leagueMembers,
  mockFetch,
  requestPath,
} from "../test/fixtures";
import { MembersSection } from "./MembersSection";

function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: "signed-in",
    user: adminUser,
    bootError: null,
    login: vi.fn(),
    signup: vi.fn(),
    refreshUser: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  };
}

function renderSection(
  onSelfRemoved = vi.fn(),
  auth: AuthContextValue = authValue(),
  leagueId = 1,
) {
  return render(
    <AuthContext.Provider value={auth}>
      <MembersSection leagueId={leagueId} onSelfRemoved={onSelfRemoved} />
    </AuthContext.Provider>,
  );
}

function member(overrides: Partial<LeagueMemberSummary>): LeagueMemberSummary {
  return {
    user_id: 99,
    email: "other@example.com",
    role: "member",
    owner_id: null,
    owner_name: null,
    has_credentials: false,
    ...overrides,
  };
}

interface MembersMutable {
  members: LeagueMemberSummary[];
  deleted?: number;
}

function membersFetch(mutable: MembersMutable) {
  return mockFetch((url, init) => {
    const path = requestPath(url);
    if (path === "/api/v1/leagues/1/members" && (init.method ?? "GET") === "GET") {
      return jsonResponse({ members: mutable.members });
    }
    const match = path.match(/^\/api\/v1\/leagues\/1\/members\/(\d+)$/);
    if (match !== null && init.method === "DELETE") {
      const userId = Number(match[1]);
      mutable.deleted = userId;
      mutable.members = mutable.members.filter((entry) => entry.user_id !== userId);
      return new Response(null, { status: 204 });
    }
    return errorResponse(404, { code: "not_found", message: path });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MembersSection", () => {
  it("lists every member with email, role, owner, and credential status", async () => {
    mockFetch(() => jsonResponse({ members: leagueMembers }));

    renderSection();

    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    const adminRow = screen.getByRole("row", { name: /admin@example.com/ });
    expect(within(adminRow).getByText("Admin")).toBeInTheDocument();
    expect(within(adminRow).getByText("Alex")).toBeInTheDocument();
    expect(within(adminRow).getByText("Stored")).toBeInTheDocument();
    const memberRow = screen.getByRole("row", { name: /member@example.com/ });
    expect(within(memberRow).getByText("Member")).toBeInTheDocument();
    expect(within(memberRow).getByText("None")).toBeInTheDocument();
  });

  it("confirms a removal by naming the member and removes only their membership", async () => {
    const user = userEvent.setup();
    const mutable: MembersMutable = { members: leagueMembers };
    const fetchMock = membersFetch(mutable);
    renderSection();

    const memberRow = await screen.findByRole("row", { name: /member@example.com/ });
    await user.click(within(memberRow).getByRole("button", { name: "Remove" }));

    const dialog = screen.getByRole("dialog", { name: "Remove member@example.com?" });
    expect(dialog).toHaveTextContent("Their account and any other leagues are not affected.");
    await user.click(within(dialog).getByRole("button", { name: "Remove member" }));

    expect(await screen.findByText("Removed member@example.com from this league.")).toBeVisible();
    expect(mutable.deleted).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/leagues/1/members/2"),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(screen.queryByText("member@example.com")).not.toBeInTheDocument();
  });

  it("warns when the removed member is the only one with stored credentials", async () => {
    const user = userEvent.setup();
    const withSecondAdmin = [
      member({
        user_id: 1,
        email: "admin@example.com",
        role: "admin",
        has_credentials: true,
      }),
      member({ user_id: 3, email: "peer@example.com", role: "admin" }),
    ];
    membersFetch({ members: withSecondAdmin });
    renderSection();

    const adminRow = await screen.findByRole("row", { name: /^admin@example\.com/ });
    await user.click(within(adminRow).getByRole("button", { name: "Remove" }));

    expect(screen.getByText(/Refresh will stop working after this removal/)).toBeInTheDocument();
  });

  it("does not offer removal for the league's last admin", async () => {
    mockFetch(() =>
      jsonResponse({
        members: [
          member({
            user_id: 1,
            email: "admin@example.com",
            role: "admin",
            has_credentials: false,
          }),
        ],
      }),
    );
    renderSection();

    const adminRow = await screen.findByRole("row", { name: /admin@example.com/ });
    expect(within(adminRow).getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(within(adminRow).getByText(/last admin cannot be removed/)).toBeVisible();
  });

  it("warns before removing yourself and leaves the page after success", async () => {
    const user = userEvent.setup();
    const onSelfRemoved = vi.fn();
    membersFetch({
      members: [
        member({
          user_id: 1,
          email: "admin@example.com",
          role: "admin",
          has_credentials: true,
        }),
        member({ user_id: 3, email: "peer@example.com", role: "admin", has_credentials: true }),
      ],
    });
    renderSection(onSelfRemoved);

    const adminRow = await screen.findByRole("row", { name: /^admin@example\.com/ });
    await user.click(within(adminRow).getByRole("button", { name: "Remove" }));

    const dialog = screen.getByRole("dialog", { name: "Remove admin@example.com?" });
    expect(dialog).toHaveTextContent("This is your own membership.");
    await user.click(within(dialog).getByRole("button", { name: "Remove member" }));

    expect(onSelfRemoved).toHaveBeenCalledTimes(1);
  });

  it("shows the server error inside the confirmation and keeps the member", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/members" && (init.method ?? "GET") === "GET") {
        return jsonResponse({ members: leagueMembers });
      }
      if (init.method === "DELETE") {
        return errorResponse(409, { code: "last_admin", message: "Keep at least one admin" });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    renderSection();

    const memberRow = await screen.findByRole("row", { name: /member@example.com/ });
    await user.click(within(memberRow).getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove member" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Keep at least one admin");
    expect(screen.getByRole("dialog", { name: "Remove member@example.com?" })).toBeVisible();
  });

  it("shows loading and error states for the member list", async () => {
    mockFetch(() => errorResponse(500, { code: "boom", message: "Members unavailable" }));
    renderSection();

    expect(await screen.findByRole("alert")).toHaveTextContent("Members unavailable");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
