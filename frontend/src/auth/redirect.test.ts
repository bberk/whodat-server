import { describe, expect, it } from "vitest";

import { redirectTarget } from "./redirect";

function from(pathname: string, search?: string) {
  return { from: { pathname, search } };
}

describe("redirectTarget", () => {
  it("accepts a same-origin path and keeps its query string", () => {
    expect(redirectTarget(from("/leagues/3/owner"))).toBe("/leagues/3/owner");
    expect(redirectTarget(from("/leagues/3/owner", "?tab=vp"))).toBe("/leagues/3/owner?tab=vp");
  });

  it("rejects a protocol-relative host", () => {
    expect(redirectTarget(from("//evil.com"))).toBe("/");
    expect(redirectTarget(from("//evil.com/leagues"))).toBe("/");
  });

  it("rejects an absolute URL with a scheme", () => {
    expect(redirectTarget(from("https://evil.com"))).toBe("/");
    expect(redirectTarget(from("javascript:alert(1)"))).toBe("/");
    expect(redirectTarget(from("javascript:"))).toBe("/");
  });

  it("rejects a backslash after the leading slash", () => {
    expect(redirectTarget(from("/\\evil.com"))).toBe("/");
    expect(redirectTarget(from("/\\evil.com/leagues"))).toBe("/");
  });

  it("falls back to the root for empty or malformed state", () => {
    expect(redirectTarget(undefined)).toBe("/");
    expect(redirectTarget(null)).toBe("/");
    expect(redirectTarget({})).toBe("/");
    expect(redirectTarget(from(""))).toBe("/");
    expect(redirectTarget(from("/leagues", "tab=vp"))).toBe("/");
    expect(redirectTarget({ from: { pathname: 7 } })).toBe("/");
  });
});
