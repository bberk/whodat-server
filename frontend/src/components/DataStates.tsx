import type { StandingsState } from "../standings/useStandingsData";

const card =
  "mt-3 rounded-xl border border-dashed border-gray-300 bg-white p-6 text-center text-gray-700";

export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className={card}>
      <div className="mx-auto h-3 w-4/5 animate-pulse rounded bg-gray-200" />
      <div className="mx-auto mt-2.5 h-3 w-3/5 animate-pulse rounded bg-gray-200" />
      <div className="mx-auto mt-2.5 h-3 w-3/4 animate-pulse rounded bg-gray-200" />
      <p className="mt-3 text-[13px] text-gray-500">{label}</p>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className={card}>
      <div
        aria-hidden="true"
        className="mx-auto mb-1 flex h-9 w-9 items-center justify-center rounded-full border-2 border-dashed border-gray-300 text-gray-500"
      >
        0
      </div>
      <p className="text-sm font-semibold text-gray-700">{title}</p>
      <p className="mt-1 text-[13px] text-gray-500">{detail}</p>
    </div>
  );
}

export function ErrorState({ onRetry, message }: { onRetry: () => void; message?: string }) {
  return (
    <div role="alert" className={card}>
      <div
        aria-hidden="true"
        className="mx-auto mb-1 flex h-9 w-9 items-center justify-center rounded-full border-2 border-red-700 text-red-700"
      >
        !
      </div>
      <p className="text-sm font-semibold text-gray-700">We couldn&rsquo;t load this view</p>
      <p className="mt-1 text-[13px] text-gray-500">
        {message ?? "Check your connection and try again."}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-[13px] text-gray-700 hover:border-brand hover:text-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        Retry
      </button>
    </div>
  );
}

export interface DataStateProps {
  state: StandingsState;
  loadingLabel: string;
  emptyTitle: string;
  emptyDetail: string;
  onRetry: () => void;
}

/** Render the loading/empty/error placeholder for a data view, or nothing once it is ready. */
export function DataState({
  state,
  loadingLabel,
  emptyTitle,
  emptyDetail,
  onRetry,
}: DataStateProps) {
  if (state.status === "loading") {
    return <LoadingState label={loadingLabel} />;
  }
  if (state.status === "error") {
    return <ErrorState onRetry={onRetry} message={state.message} />;
  }
  if (state.status === "empty") {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }
  return null;
}
