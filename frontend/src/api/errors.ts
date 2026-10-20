/** Turn an unknown rejection into the parts a form can render. */

import { ApiError } from "./client";

export interface DisplayError {
  message: string;
  fieldErrors: Readonly<Record<string, string>>;
  retryAfter: number | null;
  status: number | null;
}

function fieldErrorMap(error: ApiError): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const entry of error.fieldErrors) {
    if (!(entry.field in fields)) {
      fields[entry.field] = entry.message;
    }
  }
  return fields;
}

/** Describe an API failure, including the 429 retry window when the server supplied one. */
export function toDisplayError(error: unknown): DisplayError {
  if (!(error instanceof ApiError)) {
    return {
      message: error instanceof Error ? error.message : "Something went wrong.",
      fieldErrors: {},
      retryAfter: null,
      status: null,
    };
  }
  const retry =
    error.status === 429
      ? error.retryAfter === null
        ? " Too many attempts. Try again shortly."
        : ` Too many attempts. Try again in ${error.retryAfter} second${
            error.retryAfter === 1 ? "" : "s"
          }.`
      : "";
  return {
    message: `${error.message}${retry}`,
    fieldErrors: fieldErrorMap(error),
    retryAfter: error.retryAfter,
    status: error.status,
  };
}
