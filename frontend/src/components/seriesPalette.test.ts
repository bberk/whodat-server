/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { SERIES_STYLES } from "./series";

/** The CSS source defines the light values on `:root` and the dark overrides on `:root.dark`. */
const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
const darkStart = indexCss.indexOf(":root.dark");
const lightBlock = indexCss.slice(0, darkStart);
const darkBlock = indexCss.slice(darkStart);

const COUNT = SERIES_STYLES.length;

function palette(block: string): string[] {
  return Array.from({ length: COUNT }, (_, index) => {
    const match = new RegExp(`--series-${index}:\\s*([^;]+);`).exec(block);
    return match?.[1]?.trim() ?? "";
  });
}

describe("chart series palette", () => {
  it("defines every series variable in both the light and the dark block", () => {
    expect(darkStart).toBeGreaterThan(0);
    for (const value of palette(lightBlock)) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/);
    }
    for (const value of palette(darkBlock)) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("does not reuse the light-only palette on dark surfaces", () => {
    const light = palette(lightBlock);
    const dark = palette(darkBlock);
    expect(dark).not.toEqual(light);
    expect(new Set(dark).size).toBe(COUNT);
  });
});
