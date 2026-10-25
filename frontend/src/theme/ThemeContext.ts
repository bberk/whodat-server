import { createContext, useContext } from "react";

import type { ResolvedTheme, ThemePreference } from "./theme";

export interface ThemeContextValue {
  /** The visitor's stored choice, or "system" when they have never picked one. */
  preference: ThemePreference;
  /** The theme actually applied right now (system preference resolved). */
  resolved: ResolvedTheme;
  /** Persist an explicit choice, or "system" to follow the OS again. */
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

/** Read the theme state. Throws outside a provider so a missing provider fails loudly in dev. */
export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error("useTheme must be used inside a ThemeProvider");
  }
  return value;
}
