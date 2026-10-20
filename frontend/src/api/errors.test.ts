import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { toDisplayError } from "./errors";

describe("toDisplayError", () => {
  it("passes through a plain error message", () => {
    expect(toDisplayError(new Error("boom"))).toEqual({
      message: "boom",
      fieldErrors: {},
      retryAfter: null,
      status: null,
    });
  });

  it("describes an unknown rejection", () => {
    expect(toDisplayError("nope")).toEqual({
      message: "Something went wrong.",
      fieldErrors: {},
      retryAfter: null,
      status: null,
    });
  });

  it("keeps the first message for each field and the API status", () => {
    const error = new ApiError("Invalid input", {
      status: 422,
      fieldErrors: [
        { field: "email", message: "first message" },
        { field: "email", message: "second message" },
        { field: "password", message: "required" },
      ],
    });

    expect(toDisplayError(error)).toEqual({
      message: "Invalid input",
      fieldErrors: { email: "first message", password: "required" },
      retryAfter: null,
      status: 422,
    });
  });

  it("describes a 429 without a retry window", () => {
    const error = new ApiError("Too many requests", { status: 429 });
    expect(toDisplayError(error).message).toBe(
      "Too many requests Too many attempts. Try again shortly.",
    );
  });

  it("uses a singular second for a one-second retry window", () => {
    const error = new ApiError("Too many requests", { status: 429, retryAfter: 1 });
    expect(toDisplayError(error).message).toBe(
      "Too many requests Too many attempts. Try again in 1 second.",
    );
  });
});
