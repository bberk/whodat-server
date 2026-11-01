const PLACES = {
  1: { emoji: "🏆", label: "Champion" },
  2: { emoji: "🥈", label: "Runner-up" },
  3: { emoji: "🥉", label: "Third place" },
} as const;

type FinalPlace = keyof typeof PLACES;

function isFinalPlace(place: number | null): place is FinalPlace {
  return place === 1 || place === 2 || place === 3;
}

/**
 * The season's final podium place, from the provider-reported finishing position after the
 * playoffs. Anything other than first, second, or third (including "not reported yet") renders
 * nothing, so a season in progress never shows a trophy.
 */
export function FinalPlaceBadge({ place }: { place: number | null }) {
  if (!isFinalPlace(place)) {
    return null;
  }
  const { emoji, label } = PLACES[place];
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="inline-flex flex-none items-center text-[13px] leading-none"
    >
      {emoji}
    </span>
  );
}

/** Explain the podium emoji once near the standings, including for readers who cannot use title. */
export function FinalPlaceLegend() {
  return (
    <ul
      aria-label="Final placing legend"
      className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-subtle"
    >
      {([1, 2, 3] as const).map((place) => (
        <li key={place} className="inline-flex items-center gap-1.5">
          <FinalPlaceBadge place={place} />
          <span>{PLACES[place].label}</span>
        </li>
      ))}
    </ul>
  );
}
