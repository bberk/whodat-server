/**
 * A thin fetch client for the Victory Points API.
 *
 * Every request sends cookies (`credentials: "include"`) because the backend authenticates with
 * an httpOnly session cookie. Responses are JSON; failures are parsed into an {@link ApiError}
 * that carries the HTTP status, the backend's structured `code`/`message` (when present), field
 * errors from a 422 validation response, and the `Retry-After` header from a 429.
 */

const DEFAULT_BASE_URL = "http://localhost:8000";

export interface ApiFieldError {
  field: string;
  message: string;
}

/** A failed API call. `status` is 0 when the request never reached the server. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly fieldErrors: readonly ApiFieldError[];
  readonly retryAfter: number | null;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string | null;
      fieldErrors?: readonly ApiFieldError[];
      retryAfter?: number | null;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? null;
    this.fieldErrors = options.fieldErrors ?? [];
    this.retryAfter = options.retryAfter ?? null;
  }
}

/** True when an error means the session is missing or expired. */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

type UnauthorizedListener = () => void;

const unauthorizedListeners = new Set<UnauthorizedListener>();

/**
 * Run `listener` whenever any API request returns 401, so the auth layer can drop a session that
 * expired mid-visit. Returns a function that unsubscribes. A 401 from the initial `/me` call is
 * included; the auth layer decides whether it was signed in at the time.
 */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

function notifyUnauthorized(): void {
  for (const listener of unauthorizedListeners) {
    listener();
  }
}

/** The configured API origin, without a trailing slash. */
export function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined;
  return (configured?.trim() || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function retryAfterSeconds(headers: Headers): number | null {
  const raw = headers.get("Retry-After");
  if (raw === null) {
    return null;
  }
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function fieldErrorsFrom(detail: unknown): ApiFieldError[] {
  if (!Array.isArray(detail)) {
    return [];
  }
  const errors: ApiFieldError[] = [];
  for (const entry of detail) {
    if (!isRecord(entry)) {
      continue;
    }
    const location = Array.isArray(entry.loc) ? entry.loc : [];
    const last = location[location.length - 1];
    const field = typeof last === "string" || typeof last === "number" ? String(last) : "";
    const message = typeof entry.msg === "string" ? entry.msg : "Invalid value";
    if (field !== "") {
      errors.push({ field, message });
    }
  }
  return errors;
}

function parseError(status: number, headers: Headers, payload: unknown): ApiError {
  const retryAfter = retryAfterSeconds(headers);
  const detail = isRecord(payload) ? payload.detail : undefined;

  if (isRecord(detail)) {
    const message =
      typeof detail.message === "string"
        ? detail.message
        : typeof detail.code === "string"
          ? detail.code
          : `Request failed (${status})`;
    const code = typeof detail.code === "string" ? detail.code : null;
    return new ApiError(message, { status, code, retryAfter });
  }

  const fieldErrors = fieldErrorsFrom(detail);
  if (fieldErrors.length > 0) {
    return new ApiError(fieldErrors[0].message, { status, fieldErrors, retryAfter });
  }

  if (typeof detail === "string" && detail.trim() !== "") {
    return new ApiError(detail, { status, retryAfter });
  }

  return new ApiError(`Request failed (${status})`, { status, retryAfter });
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.trim() === "") {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * Send one API request and return the parsed JSON body.
 *
 * @throws {ApiError} for every non-2xx response and for a network failure (`status: 0`).
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method: options.method ?? "GET",
      credentials: "include",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("Could not reach the API. Check your connection and try again.", {
      status: 0,
    });
  }

  const payload = await readBody(response);
  if (!response.ok) {
    if (response.status === 401) {
      notifyUnauthorized();
    }
    throw parseError(response.status, response.headers, payload);
  }
  return payload as T;
}
