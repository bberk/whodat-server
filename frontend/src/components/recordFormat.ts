const KEYCAP_DIGITS = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"] as const;
const KEYCAP_TEN = "🔟";

/**
 * The visible count prefix for a record tally: nothing for one, keycap digits for 2-9, `🔟` for
 * ten, and keycap digits for larger counts. The count is left out entirely for zero (the caller
 * hides the tally), so `1` renders as just the record emoji while `3` renders as `3️⃣`.
 */
export function formatRecordCount(count: number): string {
  if (count <= 1) {
    return "";
  }
  if (count === 10) {
    return KEYCAP_TEN;
  }
  return String(count)
    .split("")
    .map((digit) => KEYCAP_DIGITS[Number(digit)])
    .join("");
}
