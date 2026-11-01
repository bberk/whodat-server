import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatRecordCount } from "./recordFormat";
import { SeasonRecords, SeasonRecordsLegend } from "./SeasonRecords";

describe("formatRecordCount", () => {
  it("omits the count for zero and one and uses keycap digits above one", () => {
    expect(formatRecordCount(0)).toBe("");
    expect(formatRecordCount(1)).toBe("");
    expect(formatRecordCount(3)).toBe("3️⃣");
    expect(formatRecordCount(9)).toBe("9️⃣");
    expect(formatRecordCount(10)).toBe("🔟");
    expect(formatRecordCount(12)).toBe("1️⃣2️⃣");
  });
});

describe("SeasonRecords", () => {
  it("renders one championship as a bare trophy and several with a keycap count", () => {
    const { rerender } = render(<SeasonRecords championships={1} lastPlaces={0} />);
    expect(screen.getByRole("img", { name: "1 championship" })).toHaveTextContent("🏆");
    expect(screen.getByRole("img", { name: "1 championship" }).textContent).not.toContain("1️⃣");

    rerender(<SeasonRecords championships={3} lastPlaces={0} />);
    expect(screen.getByRole("img", { name: "3 championships" })).toHaveTextContent("3️⃣🏆");
  });

  it("shows last-place finishes with the same count style", () => {
    render(<SeasonRecords championships={0} lastPlaces={2} />);
    expect(screen.getByRole("img", { name: "2 last-place finishes" })).toHaveTextContent("2️⃣💩");
  });

  it("renders nothing when a franchise has no records", () => {
    const { container } = render(<SeasonRecords championships={0} lastPlaces={0} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains both emoji in text, not colour or emoji alone", () => {
    render(<SeasonRecordsLegend />);
    expect(screen.getByText(/championships/)).toBeInTheDocument();
    expect(screen.getByText(/last-place regular-season finishes/)).toBeInTheDocument();
  });
});
