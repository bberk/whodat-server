import { formatRecordCount } from "./format";

function plural(count: number, singular: string, pluralForm: string): string {
  return count === 1 ? `1 ${singular}` : `${count} ${pluralForm}`;
}

export interface SeasonRecordsProps {
  championships: number;
  lastPlaces: number;
}

/**
 * All-time franchise records beside a team: championships (🏆) and last-place regular-season
 * finishes (💩). The count is a keycap prefix when it is more than one (`3️⃣🏆`). Each tally has a
 * spelled-out accessible name, so the emoji is never the only signal and zero records render
 * nothing.
 */
export function SeasonRecords({ championships, lastPlaces }: SeasonRecordsProps) {
  const records = [
    {
      key: "championships",
      count: championships,
      emoji: "🏆",
      label: plural(championships, "championship", "championships"),
    },
    {
      key: "last-places",
      count: lastPlaces,
      emoji: "💩",
      label: plural(lastPlaces, "last-place finish", "last-place finishes"),
    },
  ].filter((record) => record.count > 0);

  if (records.length === 0) {
    return null;
  }

  return (
    <span className="inline-flex flex-none items-center gap-1 text-[13px] leading-none">
      {records.map((record) => (
        <span key={record.key} role="img" aria-label={record.label} title={record.label}>
          <span aria-hidden="true">
            {formatRecordCount(record.count)}
            {record.emoji}
          </span>
        </span>
      ))}
    </span>
  );
}

/** A short plain-text key for the two record emoji used next to a team. */
export function SeasonRecordsLegend() {
  return (
    <p className="mt-2 text-[12.5px] text-ink-subtle">
      <span aria-hidden="true">🏆</span> championships · <span aria-hidden="true">💩</span>{" "}
      last-place regular-season finishes
    </p>
  );
}
