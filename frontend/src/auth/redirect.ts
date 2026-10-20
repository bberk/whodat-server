/** True when a browser may strip or normalize a character into a different origin. */
function hasUnsafeCharacters(target: string): boolean {
  for (const character of target) {
    const code = character.codePointAt(0) ?? 0;
    if (character === "\\" || code < 0x20 || code === 0x7f) {
      return true;
    }
  }
  return false;
}

/** A leading scheme such as `javascript:` or `https:`. */
const SCHEME_PREFIX = /^[a-z][a-z0-9+.-]*:/i;

/** A fixed origin used only to let the URL parser resolve relative paths. */
const BASE_ORIGIN = "https://app.invalid";

/**
 * True for an absolute path that stays on this origin, such as `/leagues/3/owner?tab=vp`.
 *
 * Rejects protocol-relative targets (`//evil.com`, `/\evil.com`), schemes (`javascript:`,
 * `https:`), control characters a browser might strip, and anything the URL parser resolves to a
 * different origin.
 */
function isSameOriginPath(target: string): boolean {
  if (!target.startsWith("/") || target.startsWith("//")) {
    return false;
  }
  if (SCHEME_PREFIX.test(target) || hasUnsafeCharacters(target)) {
    return false;
  }
  try {
    return new URL(target, BASE_ORIGIN).origin === BASE_ORIGIN;
  } catch {
    return false;
  }
}

/** The route to return to after login or signup, from the guard's router state. */
export function redirectTarget(state: unknown): string {
  if (typeof state !== "object" || state === null || !("from" in state)) {
    return "/";
  }
  const from = (state as { from?: unknown }).from;
  if (typeof from !== "object" || from === null) {
    return "/";
  }
  const { pathname, search } = from as { pathname?: unknown; search?: unknown };
  if (typeof pathname !== "string") {
    return "/";
  }
  if (typeof search === "string" && search !== "" && !search.startsWith("?")) {
    return "/";
  }
  const target = `${pathname}${typeof search === "string" ? search : ""}`;
  return isSameOriginPath(target) ? target : "/";
}
