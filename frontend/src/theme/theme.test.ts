import { afterEach, describe, expect, it } from "vitest";

import {
  DARK_MEDIA_QUERY,
  THEME_STORAGE_KEY,
  applyResolvedTheme,
  isThemePreference,
  persistThemePreference,
  readThemePreference,
  resolveTheme,
  systemPrefersDark,
} from "./theme";

function fakeStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

function throwingStorage(): Storage {
  return {
    get length() {
      return 0;
    },
    clear: () => {
      throw new Error("blocked");
    },
    getItem: () => {
      throw new Error("blocked");
    },
    key: () => null,
    removeItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
}

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
  document.documentElement.className = "";
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.colorScheme = "";
});

describe("isThemePreference", () => {
  it("accepts only the three supported preferences", () => {
    expect(isThemePreference("system")).toBe(true);
    expect(isThemePreference("light")).toBe(true);
    expect(isThemePreference("dark")).toBe(true);
    expect(isThemePreference("sepia")).toBe(false);
    expect(isThemePreference(null)).toBe(false);
  });
});

describe("readThemePreference", () => {
  it("defaults to system when the visitor never chose", () => {
    expect(readThemePreference(fakeStorage())).toBe("system");
  });

  it("restores an explicit choice", () => {
    expect(readThemePreference(fakeStorage({ [THEME_STORAGE_KEY]: "dark" }))).toBe("dark");
  });

  it("falls back to system for an unknown stored value", () => {
    expect(readThemePreference(fakeStorage({ [THEME_STORAGE_KEY]: "sepia" }))).toBe("system");
  });

  it("falls back to system when storage is unavailable", () => {
    expect(readThemePreference(null)).toBe("system");
    expect(readThemePreference(throwingStorage())).toBe("system");
  });
});

describe("persistThemePreference", () => {
  it("stores an explicit choice", () => {
    const storage = fakeStorage();
    persistThemePreference("dark", storage);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("clears the key for system so the OS preference applies again", () => {
    const storage = fakeStorage({ [THEME_STORAGE_KEY]: "light" });
    persistThemePreference("system", storage);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("does not throw when storage is blocked", () => {
    expect(() => persistThemePreference("dark", null)).not.toThrow();
    expect(() => persistThemePreference("dark", throwingStorage())).not.toThrow();
  });
});

describe("resolveTheme", () => {
  it("follows the system preference in system mode", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("keeps an explicit choice regardless of the system preference", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("systemPrefersDark", () => {
  it("reports false where matchMedia is unavailable", () => {
    expect(systemPrefersDark()).toBe(false);
  });

  it("reads the dark-scheme media query", () => {
    const matchMedia = (query: string) => ({ matches: query === DARK_MEDIA_QUERY });
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: matchMedia,
    });
    expect(systemPrefersDark()).toBe(true);
  });
});

describe("applyResolvedTheme", () => {
  it("adds the dark class and colour scheme for dark", () => {
    applyResolvedTheme(document, "dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("removes the dark class for light", () => {
    applyResolvedTheme(document, "dark");
    applyResolvedTheme(document, "light");
    expect(document.documentElement).not.toHaveClass("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
