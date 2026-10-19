import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the standings dashboard and labels the data as illustrative", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: /standings/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/illustrative data/i);
  });
});
