export interface DraftYearTabsProps {
  years: number[];
  selectedYear: number;
  onSelectYear: (year: number) => void;
  isLoading?: boolean;
}

/**
 * Draft Year Selector Tabs.
 *
 * Allows switching between upcoming auction draft years to view projected auction budgets.
 */
export function DraftYearTabs({
  years,
  selectedYear,
  onSelectYear,
  isLoading = false,
}: DraftYearTabsProps) {
  if (years.length === 0) {
    return null;
  }

  return (
    <div
      role="tablist"
      aria-label="Draft Years"
      className="flex flex-wrap items-center gap-2 border-b border-line pb-2"
    >
      <span className="mr-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
        Draft Year:
      </span>
      {years.map((year) => {
        const isSelected = year === selectedYear;
        return (
          <button
            key={year}
            type="button"
            role="tab"
            aria-selected={isSelected}
            aria-controls={`budget-panel-${year}`}
            id={`tab-year-${year}`}
            disabled={isLoading && !isSelected}
            onClick={() => onSelectYear(year)}
            className={`inline-flex items-center rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              isSelected
                ? "bg-brand text-brand-foreground shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                : "bg-surface-strong text-ink hover:bg-surface-emphasis hover:text-ink-strong"
            } ${isLoading && !isSelected ? "cursor-not-allowed opacity-50" : ""}`}
          >
            <span>{year} Draft</span>
          </button>
        );
      })}
    </div>
  );
}
