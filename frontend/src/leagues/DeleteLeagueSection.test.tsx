import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, mockFetch, requestPath } from "../test/fixtures";
import { DeleteLeagueSection } from "./DeleteLeagueSection";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DeleteLeagueSection", () => {
  it("only enables deletion after the exact league name is typed", async () => {
    const user = userEvent.setup();
    render(<DeleteLeagueSection leagueId={1} leagueName="Alpha League" onDeleted={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Delete league permanently" });
    expect(button).toBeDisabled();

    const input = screen.getByLabelText("Type the league name to confirm");
    await user.type(input, "alpha league");
    expect(button).toBeDisabled();

    await user.clear(input);
    await user.type(input, "Alpha League");
    expect(button).toBeEnabled();
  });

  it("deletes only this league, then hands control back to the page", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1" && init.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      return errorResponse(404, { code: "not_found", message: path });
    });
    render(<DeleteLeagueSection leagueId={1} leagueName="Alpha League" onDeleted={onDeleted} />);

    await user.type(screen.getByLabelText("Type the league name to confirm"), "Alpha League");
    await user.click(screen.getByRole("button", { name: "Delete league permanently" }));

    expect(onDeleted).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/leagues/1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("keeps the league and shows the error when deletion fails", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    mockFetch(() =>
      errorResponse(403, { code: "forbidden", message: "Only an admin may perform this action" }),
    );
    render(<DeleteLeagueSection leagueId={1} leagueName="Alpha League" onDeleted={onDeleted} />);

    await user.type(screen.getByLabelText("Type the league name to confirm"), "Alpha League");
    await user.click(screen.getByRole("button", { name: "Delete league permanently" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only an admin may perform this action",
    );
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
