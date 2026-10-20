import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { StandingsState } from "../standings/useStandingsData";
import { historyResponse, standingsResponse } from "../test/fixtures";
import { DataState, EmptyState, ErrorState, LoadingState } from "./DataStates";

describe("LoadingState", () => {
  it("announces that a view is loading", () => {
    render(<LoadingState label="Loading standings…" />);
    expect(screen.getByRole("status", { name: "Loading standings…" })).toBeInTheDocument();
    expect(screen.getByText("Loading standings…")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("explains that there is no data yet", () => {
    render(<EmptyState title="No completed weeks yet" detail="Standings appear later." />);
    expect(screen.getByText("No completed weeks yet")).toBeInTheDocument();
    expect(screen.getByText("Standings appear later.")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("is an alert and retries on demand", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState onRetry={onRetry} message="The API is unavailable." />);
    expect(screen.getByRole("alert")).toHaveTextContent("The API is unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("DataState", () => {
  const base = {
    loadingLabel: "Loading standings…",
    emptyTitle: "No completed weeks yet",
    emptyDetail: "Standings appear later.",
    onRetry: () => {},
  };

  it("renders the loading placeholder", () => {
    render(<DataState {...base} state={{ status: "loading" }} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the error placeholder", () => {
    render(<DataState {...base} state={{ status: "error", message: "boom" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("renders the empty placeholder", () => {
    render(<DataState {...base} state={{ status: "empty" }} />);
    expect(screen.getByText("No completed weeks yet")).toBeInTheDocument();
  });

  it("renders nothing once the view is ready", () => {
    const ready: StandingsState = {
      status: "ready",
      standings: standingsResponse,
      history: historyResponse,
    };
    const { container } = render(<DataState {...base} state={ready} />);
    expect(container).toBeEmptyDOMElement();
  });
});
