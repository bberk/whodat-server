/**
 * The VP rules summary. Shown on hover of the pointer and on keyboard focus (group-focus-within),
 * and always linked to the trigger with aria-describedby so assistive technology announces it on
 * focus regardless of the visual state. The summary states the components without a "+" prefix so
 * it never implies a signed VP value.
 */
export function VPRulesTooltip() {
  return (
    // No `absolute` positioning context of its own: the tooltip is anchored to the nearest
    // positioned ancestor (the section heading), so it stays inside the page at 360px instead of
    // extending the document's scroll width past the viewport.
    <span className="group inline-flex items-baseline gap-1.5">
      <button
        type="button"
        aria-describedby="vp-rules-tip"
        className="rounded-lg border border-line bg-surface px-2 py-0.5 text-[13px] text-brand-ink hover:border-brand-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink"
      >
        VP rules
      </button>
      <span
        id="vp-rules-tip"
        role="tooltip"
        className="absolute left-0 top-full z-30 mt-1.5 hidden w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface p-2.5 text-left text-[12.5px] font-normal leading-snug text-ink shadow-lg group-hover:block group-focus-within:block"
      >
        <strong className="font-semibold text-ink-muted">Weekly VP:</strong> 1 for a head-to-head
        win, 1 for a top-half score, 1 for the highest score, -1 for the lowest score; tied teams
        split the component. Ranked by season VP, then H2H wins, then points for.
      </span>
    </span>
  );
}
