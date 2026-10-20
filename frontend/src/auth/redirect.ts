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
  if (typeof pathname !== "string" || !pathname.startsWith("/")) {
    return "/";
  }
  return `${pathname}${typeof search === "string" ? search : ""}`;
}
