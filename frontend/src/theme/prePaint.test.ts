/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { DARK_MEDIA_QUERY, THEME_STORAGE_KEY } from "./theme";

/** The pre-paint script lives in index.html because it must run before the app bundle loads. */
const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

describe("pre-paint theme script", () => {
  it("runs before the application bundle", () => {
    expect(html.indexOf("localStorage.getItem")).toBeGreaterThan(0);
    expect(html.indexOf("localStorage.getItem")).toBeLessThan(html.indexOf("/src/main.tsx"));
  });

  it("stays in sync with the theme module", () => {
    expect(html).toContain(`"${THEME_STORAGE_KEY}"`);
    expect(html).toContain(`"${DARK_MEDIA_QUERY}"`);
    expect(html).toContain('classList.toggle("dark"');
    expect(html).toContain("style.colorScheme");
  });
});
