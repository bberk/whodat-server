import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { toDisplayError } from "./errors";

describe("toDisplayError", () => {
  it("passes through a plain Error and falls back for a non-Error rejection", () => {
    expect(toDisplayError(new Error("Network down"))).toEqual({
      message: "Network down",
      fieldErrors: {},
      retryAfter: null,
      status: null,
    });
    expect(toDisplayError("not an error")).toEqual({
      message: "Something went wrong.",
      fieldErrors: {},
      retryAfter: null,
      status: null,
    });
  });

  it("keeps the first message for a field reported twice", () => {
    const error = new ApiError("Validation failed", {
      status: 422,
      fieldErrors: [
        { field: "invite_code", message: "Field required" },
        { field: "invite_code", message: "Already used" },
        { field: "email", message: "Invalid email" },
      ],
    });
    expect(toDisplayError(error).fieldErrors).toEqual({
      invite_code: "Field required",
      email: "Invalid email",
    });
  });

  it("describes a 429 retry window with and without a server value", () => {
    expect(
      toDisplayError(new ApiError("Rate limited", { status: 429, retryAfter: null })).message,
    ).toBe("Rate limited Too many attempts. Try again shortly.");
    expect(
      toDisplayError(new ApiError("Rate limited", { status: 429, retryAfter: 1 })).message,
    ).toBe("Rate limited Too many attempts. Try again in 1 second.");
    expect(
      toDisplayError(new ApiError("Rate limited", { status: 429, retryAfter: 30 })).message,
    ).toBe("Rate limited Too many attempts. Try again in 30 seconds.");
  });

  it("leaves a non-429 message unchanged", () => {
    expect(toDisplayError(new ApiError("Not found", { status: 404 }))).toMatchObject({
      message: "Not found",
      retryAfter: null,
      status: 404,
    });
  });
});
