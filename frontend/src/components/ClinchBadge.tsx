import type { StandingsRow } from "../api/types";

export const CLINCH_LABELS = {
  Z: "top seed",
  Y: "division winner",
  X: "clinched playoff berth",
  E: "eliminated",
} as const;

export type ClinchStatus = NonNullable<StandingsRow["clinch"]>;

const ORDER: ClinchStatus[] = ["Z", "Y", "X", "E"];

/**
 * A one-character playoff designation. Its visible letter remains meaningful without colour,
 * while the accessible name and tooltip spell out what the letter means.
 */
export function ClinchBadge({ status }: { status: ClinchStatus | null }) {
  if (status === null) {
    return null;
  }
  const label = `${status} — ${CLINCH_LABELS[status]}`;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex h-5 min-w-5 flex-none items-center justify-center rounded border border-gray-400 bg-gray-50 px-1 text-[11px] font-bold text-gray-800"
    >
      {status}
    </span>
  );
}

/** Explain every designation once near the standings, including for readers who cannot use title. */
export function ClinchLegend() {
  return (
    <ul
      aria-label="Playoff designation legend"
      className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600"
    >
      {ORDER.map((status) => (
        <li key={status} className="inline-flex items-center gap-1.5">
          <ClinchBadge status={status} />
          <span>
            <strong>{status}</strong> — {CLINCH_LABELS[status]}
          </span>
        </li>
      ))}
    </ul>
  );
}
