/**
 * Shared client-side checks for form fields.
 *
 * User input is ASCII-only by product decision, while provider display text (league, team, owner
 * names) may be Unicode and is rendered as data. Keep the two paths separate: never run these
 * checks over API response text.
 */

/** Return a user-facing message when the value contains non-ASCII, or null when it is ASCII. */
export function asciiOnlyMessage(label: string, value: string): string | null {
  for (const character of value) {
    if ((character.codePointAt(0) ?? 0) > 0x7f) {
      return `${label} must contain only ASCII characters.`;
    }
  }
  return null;
}
