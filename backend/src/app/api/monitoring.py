"""Prometheus instrumentation for the FastAPI application.

The instrumentator is a module-level singleton because its default metrics register in the
process-wide :mod:`prometheus_client` registry. Building a new instrumentator for every
:func:`app.api.main.create_app` call would raise a duplicate-timeseries error the second time a
test, worker, or reload creates an application.
"""

from collections.abc import Callable

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info

from app.metrics import BUILD_INFO, USER_REQUESTS, observe_league_request

#: Scrape path. It is excluded from the request metrics and from the OpenAPI schema.
METRICS_PATH = "/metrics"


def _attribution() -> Callable[[Info], None]:
    """Return an instrumentation that tags requests with the caller and league when known.

    The caller comes from ``request.state.user_id``, set by the authentication dependency after a
    session is validated. The league comes from the route's ``league_id`` path parameter. Both are
    numeric ids, and both are recorded only when the response is 2xx and the caller is
    authenticated, so rejected probes and unknown league ids contribute no tagged series.
    """

    def instrumentation(info: Info) -> None:
        # Attribution is recorded only for an authenticated, successful request. A rejected probe
        # (401/403/404/422) or a nonexistent league id must not create a series: otherwise anyone
        # could mint unbounded `league_id` label values by requesting arbitrary ids.
        if not info.modified_status.startswith("2"):
            return
        user_id = getattr(info.request.state, "user_id", None)
        if not isinstance(user_id, int):
            return
        USER_REQUESTS.labels(str(user_id), info.method, info.modified_status).inc()
        league_id = info.request.path_params.get("league_id")
        # A DELETE removes the league's series after the handler, so attributing the delete would
        # immediately re-create one. Deletes are not page visits; skip them.
        if league_id is not None and info.method != "DELETE":
            observe_league_request(int(league_id), info.method, info.modified_status)

    return instrumentation


# The default metric closures are added exactly once, at import time. Passing them to every
# instrumented application keeps one set of series in the process-wide registry; letting each
# middleware build its own defaults would register duplicate collectors on the second app.
_instrumentator = (
    Instrumentator(
        # Keep exact status codes (429, 422, 500, ...) so refresh throttling and error dashboards
        # can distinguish them. The set of codes is small and bounded.
        should_group_status_codes=False,
        # Unmatched paths (scanners, typos) collapse to one "none" handler instead of one series
        # per raw path, which would otherwise leak cardinality straight into Prometheus.
        should_ignore_untemplated=True,
        excluded_handlers=[METRICS_PATH],
    )
    .add(metrics.default())
    .add(_attribution())
)


def configure_monitoring(app: FastAPI, *, version: str, environment: str) -> None:
    """Instrument ``app`` and expose ``/metrics`` in Prometheus text format.

    Uses route templates (for example ``/api/v1/leagues/{league_id}/standings``) as the handler
    label, never the resolved path, so per-league traffic does not multiply the series count.
    """
    BUILD_INFO.info({"version": version, "env": environment})
    _instrumentator.instrument(app).expose(
        app,
        endpoint=METRICS_PATH,
        include_in_schema=False,
        should_gzip=True,
    )
