import { useId } from "react";

export interface ProjectedWeekToggleProps {
  /** The active week, or null when the season has none. */
  week: number | null;
  checked: boolean;
  /** A short explanation shown under the control, or the reason it is disabled. */
  reason: string | null;
  onChange: (checked: boolean) => void;
}

/**
 * Page-level switch for the projected active week.
 *
 * The control is a native checkbox exposed as a switch, so it is keyboard operable and announces
 * its state without relying on colour. It is disabled rather than hidden when the season has no
 * active week, and the reason is always available as text.
 */
export function ProjectedWeekToggle({ week, checked, reason, onChange }: ProjectedWeekToggleProps) {
  const hintId = useId();
  const disabled = week === null;

  return (
    <div className="mt-3 rounded-xl border border-line bg-surface px-3 py-2.5">
      <label
        className={`flex items-center gap-3 text-[13px] font-semibold ${
          disabled ? "text-ink-faint" : "cursor-pointer text-ink"
        }`}
      >
        <input
          type="checkbox"
          role="switch"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          aria-describedby={hintId}
          className="h-4 w-4 accent-brand-ink"
        />
        <span>
          {week === null ? "Projected week unavailable" : `Include projected week ${week}`}
        </span>
      </label>
      <p id={hintId} className="mt-1 pl-7 text-[12px] text-ink-faint">
        {reason ??
          "Uses the stored ESPN projection for the active week in the standings, clinch badges, VP chart, WAPDate, and playoff odds. Elo and stored results are unchanged."}
      </p>
    </div>
  );
}
