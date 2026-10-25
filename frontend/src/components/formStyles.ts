/** Shared Tailwind class strings for forms and small controls, so tokens stay consistent. */

export const labelClass = "block text-[13px] font-semibold text-ink-muted";

export const inputClass =
  "mt-1 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-disabled focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink disabled:bg-surface-muted disabled:text-ink-disabled";

export const primaryButtonClass =
  "inline-flex items-center justify-center rounded-lg bg-brand px-3.5 py-2 text-sm font-semibold text-brand-foreground hover:bg-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink disabled:cursor-not-allowed disabled:bg-surface-disabled disabled:text-ink-subtle";

export const secondaryButtonClass =
  "inline-flex items-center justify-center rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-muted hover:border-brand-ink hover:text-brand-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink disabled:cursor-not-allowed disabled:border-line disabled:text-ink-disabled";

export const dangerButtonClass =
  "inline-flex items-center justify-center rounded-lg bg-danger px-3.5 py-2 text-sm font-semibold text-white hover:bg-danger-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger-ink-soft disabled:cursor-not-allowed disabled:bg-surface-disabled disabled:text-ink-subtle";

export const dangerSecondaryButtonClass =
  "inline-flex items-center justify-center rounded-lg border border-danger-line-strong bg-surface px-3 py-1.5 text-[13px] font-semibold text-danger-ink hover:border-danger-ink-soft hover:bg-danger-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger-ink-soft disabled:cursor-not-allowed disabled:border-line disabled:text-ink-disabled";

export const selectClass =
  "min-w-[96px] rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-ink disabled:bg-surface-muted disabled:text-ink-disabled";
