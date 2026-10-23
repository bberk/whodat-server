import { describe, expect, it } from "vitest";

import { asciiOnlyMessage } from "./formValidation";

describe("asciiOnlyMessage", () => {
  it.each(["", "plain ASCII", "with spaces", "p@ssw0rd!#$%^&*()", "2026"])(
    "accepts ASCII value %j",
    (value) => {
      expect(asciiOnlyMessage("Password", value)).toBeNull();
    },
  );

  it.each([
    ["café", "é"],
    ["🙂", "emoji"],
    ["می‌خواهم", "Persian with ZWNJ"],
    ["کاربر", "Arabic"],
    ["a\u200db", "zero-width joiner"],
    ["a\u202eb", "right-to-left override"],
    ["mixé🙂", "mixed"],
  ])("rejects non-ASCII %s (%s) with a field-specific message", (value) => {
    expect(asciiOnlyMessage("Email", value)).toBe("Email must contain only ASCII characters.");
  });
});
