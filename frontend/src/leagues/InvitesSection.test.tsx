import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, jsonResponse, mockFetch, requestBody, requestPath } from "../test/fixtures";
import { InvitesSection } from "./InvitesSection";

const created = {
  code: "raw-one-time-code-abcdefghijklmnop",
  role: "member",
  league_id: 1,
  expires_at: "2026-01-08T00:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("InvitesSection", () => {
  it("defaults to a member invite and seven days, then shows the code once", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/invites" && init.method === "POST") {
        expect(requestBody(init)).toEqual({ role: "member", expires_in_days: 7 });
        return jsonResponse(created, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });

    render(<InvitesSection leagueId={1} />);

    expect(screen.getByLabelText("Invite type")).toHaveValue("member");
    expect(screen.getByLabelText("Expires after (days)")).toHaveValue(7);

    await user.click(screen.getByRole("button", { name: "Generate invite" }));

    const codeInput = await screen.findByLabelText("Invite code");
    expect(codeInput).toHaveValue(created.code);
    expect(codeInput).toHaveAttribute("readonly");
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be retrieved again/)).toBeInTheDocument();
    expect(screen.getAllByDisplayValue(created.code)).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("generates a league-less admin invite", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/invites" && init.method === "POST") {
        expect(requestBody(init)).toEqual({ role: "admin", expires_in_days: 7 });
        return jsonResponse({ ...created, role: "admin", league_id: null }, { status: 201 });
      }
      return errorResponse(404, { code: "not_found", message: requestPath(url) });
    });
    render(<InvitesSection leagueId={1} />);

    await user.selectOptions(screen.getByLabelText("Invite type"), "admin");
    await user.click(screen.getByRole("button", { name: "Generate invite" }));

    expect(await screen.findByText(/League-less admin invite/)).toBeInTheDocument();
  });

  it("copies the exact code with the copy control", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockFetch(() => jsonResponse(created, { status: 201 }));
    render(<InvitesSection leagueId={1} />);

    await user.click(screen.getByRole("button", { name: "Generate invite" }));
    await screen.findByLabelText("Invite code");
    await user.click(screen.getByRole("button", { name: "Copy code" }));

    expect(writeText).toHaveBeenCalledWith(created.code);
    expect(await screen.findByText("Copied to the clipboard.")).toBeInTheDocument();
  });

  it("validates the expiry before calling the API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() => jsonResponse(created, { status: 201 }));
    render(<InvitesSection leagueId={1} />);

    const expiry = screen.getByLabelText("Expires after (days)");
    await user.clear(expiry);
    await user.type(expiry, "0");
    await user.click(screen.getByRole("button", { name: "Generate invite" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Expiry must be between 1 and 3650 days.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a structured API error without exposing a code", async () => {
    const user = userEvent.setup();
    mockFetch(() =>
      errorResponse(403, { code: "forbidden", message: "Only an admin may perform this action" }),
    );
    render(<InvitesSection leagueId={1} />);

    await user.click(screen.getByRole("button", { name: "Generate invite" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only an admin may perform this action",
    );
    expect(screen.queryByLabelText("Invite code")).not.toBeInTheDocument();
  });
});
