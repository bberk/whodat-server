import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WapdateResponse } from "../api/types";
import {
  emptyWapdateResponse,
  errorResponse,
  jsonResponse,
  mockFetch,
  requestPath,
  wapdateResponse,
} from "../test/fixtures";
import { WapdateSection } from "./WapdateSection";

function wapdateFetch(body: WapdateResponse) {
  return mockFetch((url) =>
    requestPath(url).endsWith("/wapdate")
      ? jsonResponse(body)
      : errorResponse(404, { code: "not_found", message: "Not found" }),
  );
}

function renderSection() {
  return render(<WapdateSection leagueId={1} season={2026} dataVersion={0} />);
}

function wapdateTable() {
  return screen.getByRole("region", { name: "WAPDate standings, scrollable horizontally" });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WapdateSection (AC-WD-08)", () => {
  it("lists only the offered periods and defaults to the current period", async () => {
    wapdateFetch(wapdateResponse);
    renderSection();

    const current = await screen.findByRole("radio", { name: /weeks 5-8 · in progress/i });
    expect(current).toBeChecked();
    expect(screen.queryByText(/The worst team in each four-week block/i)).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /weeks 1-4 · complete/i })).not.toBeChecked();
    expect(screen.queryByRole("radio", { name: /weeks 9-12/i })).not.toBeInTheDocument();

    const table = wapdateTable();
    const rows = within(table).getAllByRole("rowheader");
    expect(rows[0]).toHaveTextContent("Foxtrot");
    expect(rows[1]).toHaveTextContent("Delta");
    expect(rows[2]).toHaveTextContent("Bravo");
    expect(rows[3]).toHaveTextContent("Alpha");
    expect(screen.getByText("Weeks counted: 5, 6.")).toBeInTheDocument();
  });

  it("switches to another offered period and shows its rows and counted weeks", async () => {
    wapdateFetch(wapdateResponse);
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByRole("radio", { name: /weeks 1-4 · complete/i }));

    expect(screen.getByRole("radio", { name: /weeks 1-4 · complete/i })).toBeChecked();
    expect(screen.getByText("Weeks counted: 1, 2, 3, 4.")).toBeInTheDocument();
    const rows = within(wapdateTable()).getAllByRole("rowheader");
    expect(rows[0]).toHaveTextContent("Charlie");
    expect(rows[3]).toHaveTextContent("Alpha");
    // A completed period shows the actual result with no greying.
    expect(screen.queryByTitle("cannot finish last")).not.toBeInTheDocument();
  });

  it("falls back to the latest complete period when no period is current", async () => {
    const completedOnly: WapdateResponse = {
      ...wapdateResponse,
      periods: wapdateResponse.periods.map((period) => ({ ...period, status: "complete" })),
    };
    wapdateFetch(completedOnly);
    renderSection();

    const latest = await screen.findByRole("radio", { name: /weeks 5-8 · complete/i });
    expect(latest).toBeChecked();
    expect(screen.getByRole("radio", { name: /weeks 1-4 · complete/i })).not.toBeChecked();
  });

  it("greys a safe team and marks it in text and an accessible description", async () => {
    wapdateFetch(wapdateResponse);
    renderSection();

    const table = await screen.findByRole("region", {
      name: "WAPDate standings, scrollable horizontally",
    });
    const alphaRow = within(table)
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("Alpha"));
    expect(alphaRow).toBeDefined();
    expect(alphaRow).toHaveClass("bg-gray-50");

    const badge = screen.getByTitle("cannot finish last");
    expect(badge).toHaveTextContent("Safe");
    expect(badge).toHaveTextContent("cannot finish last");
  });

  it("shows loading, empty, and error states and retries a failed load", async () => {
    mockFetch(() => new Promise<Response>(() => {}));
    const loading = renderSection();
    expect(screen.getByRole("status", { name: "Loading WAPDate standings…" })).toBeInTheDocument();
    loading.unmount();

    wapdateFetch(emptyWapdateResponse);
    const empty = renderSection();
    expect(await screen.findByText("No WAPDate periods yet")).toBeInTheDocument();
    empty.unmount();

    let calls = 0;
    mockFetch((url) => {
      if (!requestPath(url).endsWith("/wapdate")) {
        return errorResponse(404, { code: "not_found", message: "Not found" });
      }
      calls += 1;
      return calls === 1
        ? errorResponse(500, { code: "boom", message: "The API is unavailable." })
        : jsonResponse(wapdateResponse);
    });
    const user = userEvent.setup();
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("The API is unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /weeks 5-8 · in progress/i })).toBeChecked();
    });
  });
});
