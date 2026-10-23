import { useId } from "react";

export interface InfoTooltipProps {
  /** Accessible name for the trigger, for example "About the K factor". */
  label: string;
  /** Explanation shown on hover/focus and announced through aria-describedby. */
  text: string;
  /** Stable id for tests and the aria-describedby relationship; generated when omitted. */
  id?: string;
}

/**
 * A small "?" trigger whose explanation appears on hover and on keyboard focus.
 *
 * The trigger is a real button, so it is reachable with Tab and has an accessible name. The
 * explanation is always associated through aria-describedby, not only while visually shown, so
 * assistive technology hears it on focus regardless of CSS. The wrapper is positioned so the
 * popover stays inside a narrow viewport instead of widening the page.
 */
export function InfoTooltip({ label, text, id }: InfoTooltipProps) {
  const generatedId = useId();
  const tipId = id ?? `info-${generatedId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        aria-describedby={tipId}
        className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-gray-300 bg-white text-[11px] font-bold text-gray-600 hover:border-brand hover:text-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        <span aria-hidden="true">?</span>
      </button>
      <span
        id={tipId}
        role="tooltip"
        className="absolute left-0 top-full z-40 mt-1.5 hidden w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-gray-200 bg-white p-2.5 text-left text-[12.5px] font-normal leading-snug text-gray-900 shadow-lg group-hover:block group-focus-within:block"
      >
        {text}
      </span>
    </span>
  );
}
