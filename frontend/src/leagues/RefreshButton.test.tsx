import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, jsonResponse, mockFetch, requestPath } from "../test/fixtures";
import { RefreshButton } from "./RefreshButton";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RefreshButton", () => {
  it("is disabled when the membership has no credentials", () => {
    const onRefreshed = vi.fn();
    render(<RefreshButton leagueId={1} hasCredentials={false} onRefreshed={onRefreshed} />);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
    expect(screen.getByText("Refresh needs ESPN credentials.")).toBeInTheDocument();
  });

  it("refreshes the league and reports the synced weeks", async () => {
    const user = userEvent.setup();
    const onRefreshed = vi.fn();
    const fetchMock = mockFetch((url, init) => {
      if (requestPath(url) === "/api/v1/leagues/1/refresh" && init.method === "POST") {
        return jsonResponse({
          league_id: 1,
          season: 2026,
          weeks_synced: [1, 2],
          weeks_with_vp_recomputed: [1, 2],
        });
      }
      return errorResponse(404, { code: "not_found", message: "unexpected" });
    });
    render(<RefreshButton leagueId={1} hasCredentials onRefreshed={onRefreshed} />);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Refreshed 2 weeks (W1, W2).")).toBeInTheDocument();
    expect(onRefreshed).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows a 429 Retry-After message and becomes available again", async () => {
    const user = userEvent.setup();
    mockFetch(() =>
      errorResponse(429, { code: "rate_limited", message: "League refresh is rate limited" }, 42),
    );
    render(<RefreshButton leagueId={1} hasCredentials onRefreshed={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 42 seconds");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
    });
  });

  it("reports a refresh that synced no weeks", async () => {
    const user = userEvent.setup();
    mockFetch(() =>
      jsonResponse({
        league_id: 1,
        season: 2026,
        weeks_synced: [],
        weeks_with_vp_recomputed: [],
      }),
    );
    render(<RefreshButton leagueId={1} hasCredentials onRefreshed={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByText("Refresh finished; no weeks needed syncing."),
    ).toBeInTheDocument();
  });

  it("uses the singular week label", async () => {
    const user = userEvent.setup();
    mockFetch(() =>
      jsonResponse({
        league_id: 1,
        season: 2026,
        weeks_synced: [3],
        weeks_with_vp_recomputed: [3],
      }),
    );
    render(<RefreshButton leagueId={1} hasCredentials onRefreshed={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Refreshed 1 week (W3).")).toBeInTheDocument();
  });
});
