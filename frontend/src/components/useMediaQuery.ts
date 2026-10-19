import { useEffect, useState } from "react";

/**
 * Track a CSS media query from React. Returns false where `matchMedia` is unavailable (for
 * example jsdom, which does not implement it), so the caller gets a stable, safe default.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => readMatches(query));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const list = window.matchMedia(query);
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };
    list.addEventListener("change", onChange);
    return () => {
      list.removeEventListener("change", onChange);
    };
  }, [query]);

  return matches;
}

function readMatches(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(query).matches;
}
