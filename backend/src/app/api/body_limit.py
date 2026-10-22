"""Reject request bodies above a modest, fixed size before the application parses them.

A JSON API has no legitimate need for a large upload, so a global cap keeps an oversized or
streamed body from being read into memory or handed to a schema. Both a declared
``Content-Length`` and the actual received bytes are checked, which also covers a chunked request
that declares no length. The rejection is a structured JSON 413 rather than a validation error.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Largest accepted request body. Normal JSON requests are far below this (the largest schema field
#: is a 4 KiB credential), so the cap only catches pathological payloads.
MAX_REQUEST_BODY_BYTES = 64 * 1024

_PAYLOAD_TOO_LARGE = {
    "detail": {
        "code": "payload_too_large",
        "message": "Request body is too large",
    }
}


class RequestBodyLimitMiddleware:
    """Enforce :data:`MAX_REQUEST_BODY_BYTES` on every HTTP request.

    The body is buffered only up to the limit and replayed to the application as one
    ``http.request`` message, so downstream code still sees an ordinary request body. A body that
    exceeds the limit is never passed on; the middleware answers with a 413 itself.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        """Wrap ``app`` and record the maximum number of body bytes to accept."""
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the declared and actual body size, then delegate or reject."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared_length = self._declared_length(scope)
        if declared_length is not None and declared_length > self._max_bytes:
            await self._reject(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self._max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        """Return a valid non-negative declared Content-Length, or None when absent/malformed."""
        raw = Headers(scope=scope).get("content-length")
        if raw is None:
            return None
        try:
            length = int(raw)
        except ValueError:
            return None
        return length if length >= 0 else None

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        """Send the structured 413 response."""
        response = JSONResponse(_PAYLOAD_TOO_LARGE, status_code=413)
        await response(scope, receive, send)
