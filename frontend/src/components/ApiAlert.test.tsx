import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiAlert } from "./ApiAlert";

describe("ApiAlert", () => {
  it("renders the message and per-field validation errors", () => {
    render(
      <ApiAlert
        error={{
          message: "Validation failed",
          fieldErrors: { invite_code: "Field required" },
          retryAfter: null,
          status: 422,
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Validation failed");
    expect(screen.getByRole("alert")).toHaveTextContent("invite_code: Field required");
  });

  it("renders nothing without an error", () => {
    const { container } = render(<ApiAlert error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
