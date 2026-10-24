import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClinchBadge, ClinchLegend } from "./ClinchBadge";

describe("ClinchBadge", () => {
  it("renders each letter with a full accessible explanation", () => {
    const { rerender } = render(<ClinchBadge status="Z" />);
    expect(screen.getByRole("img", { name: "Z — top seed" })).toHaveTextContent("Z");
    expect(screen.getByTitle("Z — top seed")).toBeInTheDocument();

    rerender(<ClinchBadge status="Y" />);
    expect(screen.getByRole("img", { name: "Y — division winner" })).toBeInTheDocument();
    rerender(<ClinchBadge status="X" />);
    expect(screen.getByRole("img", { name: "X — clinched playoff berth" })).toBeInTheDocument();
    rerender(<ClinchBadge status="E" />);
    expect(screen.getByRole("img", { name: "E — eliminated" })).toBeInTheDocument();
  });

  it("renders nothing when a team has no proven designation", () => {
    const { container } = render(<ClinchBadge status={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a text legend for every status, not colour alone", () => {
    render(<ClinchLegend />);
    const legend = screen.getByRole("list", { name: "Playoff designation legend" });
    expect(legend).toHaveTextContent("Z — top seed");
    expect(legend).toHaveTextContent("Y — division winner");
    expect(legend).toHaveTextContent("X — clinched playoff berth");
    expect(legend).toHaveTextContent("E — eliminated");
  });
});
