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

from app.metrics import BUILD_INFO, LEAGUE_REQUESTS, USER_REQUESTS

#: Scrape path. It is excluded from the request metrics and from the OpenAPI schema.
METRICS_PATH = "/metrics"


def _attribution() -> Callable[[Info], None]:
    """Return an instrumentation that tags requests with the caller and league when known.

    The caller comes from ``request.state.user_id``, set by the authentication dependency after a
    session is validated. The league comes from the route's ``league_id`` path parameter. Both are
    numeric ids, so an unauthenticated request or a route without a league simply contributes no
    tagged series.
    """

    def instrumentation(info: Info) -> None:
        user_id = getattr(info.request.state, "user_id", None)
        if isinstance(user_id, int):
            USER_REQUESTS.labels(str(user_id), info.method, info.modified_status).inc()
        league_id = info.request.path_params.get("league_id")
        if league_id is not None:
            LEAGUE_REQUESTS.labels(str(league_id), info.method, info.modified_status).inc()

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
