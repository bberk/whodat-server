import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectedWeekToggle } from "./ProjectedWeekToggle";

describe("ProjectedWeekToggle", () => {
  it("is an accessible switch that reports its checked state and calls back", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ProjectedWeekToggle week={7} checked={false} reason={null} onChange={onChange} />);

    const toggle = screen.getByRole("switch", { name: /include projected week 7/i });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("disables itself and explains why when the season has no active week", () => {
    render(
      <ProjectedWeekToggle
        week={null}
        checked={false}
        reason="This season has no active week to project."
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("switch", { name: /projected week unavailable/i })).toBeDisabled();
    expect(screen.getByText(/no active week to project/i)).toBeInTheDocument();
  });
});
