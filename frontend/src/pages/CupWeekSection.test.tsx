import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CupWeekSection } from "./CupWeekSection";
import { errorResponse, jsonResponse, mockFetch, requestBody, requestPath } from "../test/fixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

function cupWeekResponse(cupWeek: number | null, regularSeasonLength = 2) {
  return { season: 2026, cup_week: cupWeek, regular_season_length: regularSeasonLength };
}

describe("CupWeekSection", () => {
  it("offers no cup week or each regular-season week and saves the choice", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      const path = requestPath(url);
      if (path === "/api/v1/leagues/1/seasons/2026/cup-week" && init.method === "PUT") {
        expect(requestBody(init)).toEqual({ cup_week: 2 });
        return jsonResponse(cupWeekResponse(2));
      }
      if (path === "/api/v1/leagues/1/seasons/2026/cup-week") {
        return jsonResponse(cupWeekResponse(null));
      }
      return errorResponse(404, { code: "not_found", message: path });
    });

    render(<CupWeekSection leagueId={1} season={2026} />);

    const select = await screen.findByLabelText("Cup week for this season");
    expect(select).toHaveValue("");
    expect(
      Array.from(select.querySelectorAll("option")).map((option) => option.textContent),
    ).toEqual(["No cup week", "Week 1", "Week 2"]);

    await user.selectOptions(select, "2");
    await user.click(screen.getByRole("button", { name: "Save cup week" }));

    expect(
      await screen.findByText("Cup week saved. Standings will show the updated VP."),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Cup week saved");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows the stored cup week, and clearing it sends null", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((_url, init) => {
      if (init.method === "PUT") {
        expect(requestBody(init)).toEqual({ cup_week: null });
        return jsonResponse(cupWeekResponse(null));
      }
      return jsonResponse(cupWeekResponse(1));
    });

    render(<CupWeekSection leagueId={1} season={2026} />);

    const select = await screen.findByLabelText("Cup week for this season");
    expect(select).toHaveValue("1");
    await user.selectOptions(select, "");
    await user.click(screen.getByRole("button", { name: "Save cup week" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Cup week saved");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows an error state and retries loading the cup week", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(() =>
      errorResponse(400, { code: "invalid_season_settings", message: "Settings are not usable" }),
    );

    render(<CupWeekSection leagueId={1} season={2026} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Settings are not usable");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });

  it("shows a structured error when saving fails", async () => {
    const user = userEvent.setup();
    mockFetch((_url, init) => {
      if (init.method === "PUT") {
        return errorResponse(400, {
          code: "invalid_cup_week",
          message: "cup_week must be between 1 and the season's regular season length",
        });
      }
      return jsonResponse(cupWeekResponse(null));
    });

    render(<CupWeekSection leagueId={1} season={2026} />);
    await screen.findByLabelText("Cup week for this season");
    await user.click(screen.getByRole("button", { name: "Save cup week" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "cup_week must be between 1 and the season's regular season length",
      );
    });
  });
});
