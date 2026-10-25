import { useId } from "react";

import type { ThemePreference } from "./theme";
import { useTheme } from "./ThemeContext";

const OPTIONS: readonly { value: ThemePreference; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/** A 14px line icon for each preference; decorative, so the label carries the meaning. */
function ThemeIcon({ preference }: { preference: ThemePreference }) {
  if (preference === "light") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        width={14}
        height={14}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
      >
        <circle cx={8} cy={8} r={3} />
        <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M13 3l-1.4 1.4M4.4 11.6L3 13" />
      </svg>
    );
  }
  if (preference === "dark") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        width={14}
        height={14}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13.5 10.2A5.8 5.8 0 0 1 5.8 2.5 5.8 5.8 0 1 0 13.5 10.2Z" />
      </svg>
    );
  }
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      width={14}
      height={14}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x={1.5} y={2.5} width={13} height={9} rx={1.5} />
      <path d="M5.5 14h5M8 11.5V14" />
    </svg>
  );
}

/**
 * Three-state theme control: System, Light, or Dark.
 *
 * Native radio inputs inside a labelled fieldset give arrow-key movement, a checked state that
 * screen readers announce, and a visible focus ring on the label. The current state is also echoed
 * in a polite live region (including which theme System resolves to), so a change is announced
 * without relying on colour.
 */
export function ThemeToggle() {
  const { preference, resolved, setPreference } = useTheme();
  const generatedId = useId();
  const groupName = `theme-${generatedId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const status =
    preference === "system"
      ? `System theme, following your device (${resolved}).`
      : `${preference === "dark" ? "Dark" : "Light"} theme selected.`;

  return (
    <div className="flex items-center">
      <fieldset className="inline-flex min-w-0 items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5">
        <legend className="sr-only">Colour theme</legend>
        {OPTIONS.map((option) => {
          const checked = preference === option.value;
          return (
            <label
              key={option.value}
              className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-[12px] font-semibold focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand-ink ${
                checked ? "bg-brand-soft text-brand-ink" : "text-ink-faint hover:text-brand-ink"
              }`}
            >
              <input
                type="radio"
                name={groupName}
                value={option.value}
                checked={checked}
                onChange={() => setPreference(option.value)}
                className="sr-only"
              />
              <ThemeIcon preference={option.value} />
              <span>{option.label}</span>
            </label>
          );
        })}
      </fieldset>
      <span aria-live="polite" aria-atomic="true" className="sr-only">
        {status}
      </span>
    </div>
  );
}
