import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VPRulesTooltip } from "./VPRulesTooltip";

describe("VPRulesTooltip", () => {
  it("links the trigger to a tooltip with aria-describedby", () => {
    render(<VPRulesTooltip />);
    const trigger = screen.getByRole("button", { name: "VP rules" });
    const tooltip = screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(tooltip).toHaveAttribute("id", "vp-rules-tip");
  });

  it("shows on hover and focus so it is keyboard reachable", () => {
    render(<VPRulesTooltip />);
    expect(screen.getByRole("tooltip").className).toContain("group-focus-within:block");
    expect(screen.getByRole("tooltip").className).toContain("group-hover:block");
  });

  it("states the components without a + prefix on any value", () => {
    render(<VPRulesTooltip />);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(/head-to-head win/i);
    expect(tooltip).toHaveTextContent(/-1 for the lowest score/i);
    expect(tooltip.textContent ?? "").not.toContain("+");
  });
});
