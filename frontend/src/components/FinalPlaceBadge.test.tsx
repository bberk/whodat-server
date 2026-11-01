import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FinalPlaceBadge, FinalPlaceLegend } from "./FinalPlaceBadge";

describe("FinalPlaceBadge", () => {
  it("renders the three podium places with spelled-out accessible names", () => {
    const { rerender } = render(<FinalPlaceBadge place={1} />);
    expect(screen.getByRole("img", { name: "Champion" })).toHaveTextContent("🏆");

    rerender(<FinalPlaceBadge place={2} />);
    expect(screen.getByRole("img", { name: "Runner-up" })).toHaveTextContent("🥈");

    rerender(<FinalPlaceBadge place={3} />);
    expect(screen.getByRole("img", { name: "Third place" })).toHaveTextContent("🥉");
  });

  it("renders nothing for a missing or non-podium final position", () => {
    const { container } = render(<FinalPlaceBadge place={null} />);
    expect(container).toBeEmptyDOMElement();

    const { container: fourth } = render(<FinalPlaceBadge place={4} />);
    expect(fourth).toBeEmptyDOMElement();
  });

  it("explains the podium in a text legend", () => {
    render(<FinalPlaceLegend />);
    const legend = screen.getByRole("list", { name: "Final placing legend" });
    expect(legend).toHaveTextContent("Champion");
    expect(legend).toHaveTextContent("Runner-up");
    expect(legend).toHaveTextContent("Third place");
    // The adjacent text names each place, so the legend emoji is decorative and not announced
    // twice ("Champion Champion").
    expect(screen.queryByRole("img", { name: "Champion" })).not.toBeInTheDocument();
  });
});
