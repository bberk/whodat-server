import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the standings heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /victory points standings/i })).toBeInTheDocument();
  });
});
