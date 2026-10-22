import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, isUnauthorized } from "./client";
import { errorResponse, jsonResponse, mockFetch, requestPath } from "../test/fixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("sends cookies and a JSON body to the configured API base URL", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ id: 1 }));
    await apiRequest("/api/v1/auth/login", {
      method: "POST",
      body: { email: "a@example.com", password: "secret" },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/auth/login");
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      email: "a@example.com",
      password: "secret",
    });
    expect(requestPath(String(url))).toBe("/api/v1/auth/login");
  });

  it("parses a structured error and a 429 Retry-After window", async () => {
    mockFetch(() => errorResponse(429, { code: "rate_limited", message: "Too many requests" }, 30));
    const failure = await apiRequest("/api/v1/auth/login", { method: "POST" }).catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    const error = failure as ApiError;
    expect(error.status).toBe(429);
    expect(error.code).toBe("rate_limited");
    expect(error.message).toBe("Too many requests");
    expect(error.retryAfter).toBe(30);
  });

  it("surfaces the structured request-too-large error without request input", async () => {
    mockFetch(() =>
      errorResponse(413, {
        code: "payload_too_large",
        message: "Request body is too large",
      }),
    );
    const failure = await apiRequest("/api/v1/auth/signup", { method: "POST" }).catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    const error = failure as ApiError;
    expect(error.status).toBe(413);
    expect(error.code).toBe("payload_too_large");
    expect(error.message).toBe("Request body is too large");
    expect(error.fieldErrors).toEqual([]);
  });

  it("maps 422 validation entries to field errors and treats 401 as unauthorized", async () => {
    mockFetch(() =>
      errorResponse(422, [
        { loc: ["body", "invite_code"], msg: "Field required", type: "missing" },
      ]),
    );
    const failure = await apiRequest("/api/v1/auth/signup", { method: "POST" }).catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    const error = failure as ApiError;
    expect(error.fieldErrors).toEqual([{ field: "invite_code", message: "Field required" }]);
    expect(isUnauthorized(error)).toBe(false);

    mockFetch(() =>
      errorResponse(401, { code: "not_authenticated", message: "Authentication required" }),
    );
    const unauthorized = await apiRequest("/api/v1/me").catch((failure: unknown) => failure);
    expect(isUnauthorized(unauthorized)).toBe(true);
  });

  it("reports a network failure as a status-0 ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const failure = await apiRequest("/api/v1/me").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(0);
    expect((failure as ApiError).message).toMatch(/could not reach the api/i);
  });

  it("returns null for an empty success body and text for a non-JSON body", async () => {
    mockFetch(() => new Response("", { status: 200 }));
    await expect(apiRequest("/api/v1/me")).resolves.toBeNull();

    mockFetch(() => new Response("ok", { status: 200 }));
    await expect(apiRequest("/api/v1/me")).resolves.toBe("ok");
  });

  it("uses a string detail as the message and ignores an invalid Retry-After", async () => {
    mockFetch(
      () =>
        new Response(JSON.stringify({ detail: "Maintenance window" }), {
          status: 503,
          headers: { "Retry-After": "later" },
        }),
    );
    const failure = await apiRequest("/api/v1/me").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).message).toBe("Maintenance window");
    expect((failure as ApiError).retryAfter).toBeNull();
  });

  it("falls back through the code and generic message for an unknown error body", async () => {
    mockFetch(() => jsonResponse({ detail: { code: "teapot" } }, { status: 418 }));
    const coded = await apiRequest("/api/v1/me").catch((error: unknown) => error);
    expect((coded as ApiError).message).toBe("teapot");
    expect((coded as ApiError).code).toBe("teapot");

    mockFetch(() => jsonResponse({ detail: { other: true } }, { status: 418 }));
    const generic = await apiRequest("/api/v1/me").catch((error: unknown) => error);
    expect((generic as ApiError).message).toBe("Request failed (418)");
  });

  it("skips malformed validation entries and keeps usable field errors", async () => {
    mockFetch(() =>
      errorResponse(422, [
        null,
        { loc: [], msg: "Lost" },
        { loc: ["body", "name"] },
        { loc: ["body", 0, "team_id"], msg: "Not yours", type: "value_error" },
      ]),
    );
    const failure = await apiRequest("/api/v1/me").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).fieldErrors).toEqual([
      { field: "name", message: "Invalid value" },
      { field: "team_id", message: "Not yours" },
    ]);
  });

  it("rethrows an aborted request instead of reporting a network failure", async () => {
    const abort = new DOMException("The operation was aborted.", "AbortError");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(abort)),
    );
    await expect(apiRequest("/api/v1/me")).rejects.toBe(abort);
  });
});
