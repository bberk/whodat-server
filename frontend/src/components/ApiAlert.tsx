import type { DisplayError } from "../api/errors";

/** Render a structured API failure, including 422 field messages and a 429 retry window. */
export function ApiAlert({ error }: { error: DisplayError | null }) {
  if (error === null) {
    return null;
  }
  const fields = Object.entries(error.fieldErrors);
  return (
    <div
      role="alert"
      className="rounded-lg border border-danger-line bg-danger-surface px-3 py-2 text-[13px] text-danger-ink"
    >
      <p>{error.message}</p>
      {fields.length === 0 ? null : (
        <ul className="mt-1 list-inside list-disc">
          {fields.map(([field, message]) => (
            <li key={field}>
              <span className="font-semibold">{field}</span>: {message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
