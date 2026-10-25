import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";

import { ThemeContext, type ThemeContextValue } from "./ThemeContext";
import {
  DARK_MEDIA_QUERY,
  applyResolvedTheme,
  persistThemePreference,
  readThemePreference,
  resolveTheme,
  systemPrefersDark,
  type ThemePreference,
} from "./theme";

/**
 * Owns the theme preference and keeps the document in sync.
 *
 * The first render takes the stored preference (or "system") and the current OS setting, and the
 * layout effect applies the resolved theme before paint is committed, so a stored explicit choice
 * is honoured without waiting for an effect. The media-query listener always tracks the OS value,
 * but it only changes the applied theme while the preference is "system"; an explicit Light or Dark
 * choice ignores live system changes. Choosing "system" clears storage instead of storing a value,
 * so the visitor follows the OS again on later visits.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readThemePreference);
  const [systemDark, setSystemDark] = useState<boolean>(systemPrefersDark);
  const resolved = resolveTheme(preference, systemDark);

  useLayoutEffect(() => {
    applyResolvedTheme(document, resolved);
  }, [resolved]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia(DARK_MEDIA_QUERY);
    setSystemDark(media.matches);
    const onChange = (event: MediaQueryListEvent) => {
      setSystemDark(event.matches);
    };
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    persistThemePreference(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
