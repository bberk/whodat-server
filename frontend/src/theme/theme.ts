/**
 * Theme preference model.
 *
 * A visitor has one of three preferences: follow the operating system ("system"), or pin "light"
 * or "dark". Only an explicit choice is persisted, so a visit that never chose keeps following live
 * `prefers-color-scheme` changes. These helpers are pure and side-effect free apart from the
 * document/storage handles a caller passes in, which keeps the resolution rules testable without a
 * browser.
 */

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

/** Must match the key read by the pre-paint script in index.html. */
export const THEME_STORAGE_KEY = "vp-theme";
export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

const PREFERENCES: readonly ThemePreference[] = ["system", "light", "dark"];

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && PREFERENCES.includes(value as ThemePreference);
}

/** The browser's storage, or null where it is unavailable (for example blocked cookies). */
export function safeStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Read the stored preference. Absent or unreadable values mean "follow the system". */
export function readThemePreference(storage: Storage | null = safeStorage()): ThemePreference {
  if (storage === null) {
    return "system";
  }
  try {
    const stored = storage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** Store an explicit choice; "system" clears the key so the OS preference applies again. */
export function persistThemePreference(
  preference: ThemePreference,
  storage: Storage | null = safeStorage(),
): void {
  if (storage === null) {
    return;
  }
  try {
    if (preference === "system") {
      storage.removeItem(THEME_STORAGE_KEY);
    } else {
      storage.setItem(THEME_STORAGE_KEY, preference);
    }
  } catch {
    // A full or blocked storage quota must not break the toggle for this visit.
  }
}

/** Resolve a preference against the current OS setting; "system" defers, an explicit choice wins. */
export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

/** True when the operating system currently prefers a dark colour scheme. */
export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(DARK_MEDIA_QUERY).matches;
}

/**
 * Apply a resolved theme to the document: the `dark` class drives every Tailwind token, `data-theme`
 * gives non-Tailwind CSS and tests a stable hook, and `color-scheme` themes native form controls and
 * scrollbars to match.
 */
export function applyResolvedTheme(document: Document, theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}
