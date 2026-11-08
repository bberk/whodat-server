import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DraftYearTabs } from "./DraftYearTabs";

describe("DraftYearTabs", () => {
  it("renders draft year tabs with accessible role and labels", () => {
    render(<DraftYearTabs years={[2026, 2027, 2028]} selectedYear={2026} onSelectYear={vi.fn()} />);

    expect(screen.getByRole("tablist", { name: "Draft Years" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);

    expect(tabs[0]).toHaveTextContent("2026 Draft");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    expect(tabs[1]).toHaveTextContent("2027 Draft");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");

    expect(tabs[2]).toHaveTextContent("2028 Draft");
    expect(tabs[2]).toHaveAttribute("aria-selected", "false");
  });

  it("calls onSelectYear when a tab is clicked", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();

    render(
      <DraftYearTabs years={[2026, 2027, 2028]} selectedYear={2026} onSelectYear={onSelect} />,
    );

    const tab2027 = screen.getByRole("tab", { name: "2027 Draft" });
    await user.click(tab2027);

    expect(onSelect).toHaveBeenCalledWith(2027);
  });

  it("returns null when years array is empty", () => {
    const { container } = render(
      <DraftYearTabs years={[]} selectedYear={2026} onSelectYear={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("disables unselected tabs while loading", () => {
    render(
      <DraftYearTabs
        years={[2026, 2027, 2028]}
        selectedYear={2026}
        onSelectYear={vi.fn()}
        isLoading={true}
      />,
    );

    const tab2026 = screen.getByRole("tab", { name: "2026 Draft" });
    const tab2027 = screen.getByRole("tab", { name: "2027 Draft" });

    expect(tab2026).not.toBeDisabled();
    expect(tab2027).toBeDisabled();
  });
});
