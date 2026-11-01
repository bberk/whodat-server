"""Prometheus metric definitions shared by the API layer and the services.

The objects live in the default :mod:`prometheus_client` registry and are created once at import
time, so importing this module from more than one place is safe and idempotent.

Label values stay low-cardinality by default. Never label a general metric with a user id, league
id, account email, session, raw request path, or free-form exception text: each distinct value
creates a new time series that Prometheus keeps in memory and on disk. The two attribution counters
below are the deliberate, bounded exception: they carry numeric account and league ids only, and
nothing else is labeled with those ids.
"""

from collections import OrderedDict
from threading import Lock

from prometheus_client import Counter, Histogram, Info

#: Build and runtime identity, set once when the application is created.
BUILD_INFO = Info("app_build", "Build and runtime identity of the running backend.")

#: Provider data fetches by adapter and outcome. A ``not_found`` outcome means the provider did
#: not know the requested league season; ``error`` covers every other failure.
PROVIDER_FETCH_TOTAL = Counter(
    "app_provider_fetch_total",
    "League fetches issued to a data provider, by provider and outcome.",
    ("provider", "outcome"),
)

#: Wall-clock time spent in the first provider call of a sync (the league fetch). Buckets span
#: sub-second cache hits through a slow, remote ESPN response.
PROVIDER_FETCH_DURATION_SECONDS = Histogram(
    "app_provider_fetch_duration_seconds",
    "Wall-clock seconds spent fetching a league from a data provider.",
    ("provider",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

#: Requests attributed to the authenticated account. This is deliberately higher cardinality than
#: ``http_requests_total``: one series per active account plus method/status. The label is the
#: numeric account id, never an email, name, or session token.
USER_REQUESTS = Counter(
    "app_user_requests_total",
    "Requests attributed to the authenticated account, by numeric user id.",
    ("user_id", "method", "status"),
)

#: Upper bound on live user attribution label sets. Accounts are not deleted today, so the cap is
#: the backstop that keeps registry and Prometheus cardinality bounded as invitations add accounts.
MAX_USER_LABEL_SETS = 4096

#: Live label sets, oldest first, so the cap can evict the least recently used one.
_USER_LABEL_SETS: OrderedDict[tuple[str, str, str], None] = OrderedDict()
_USER_LABEL_SETS_LOCK = Lock()


def observe_user_request(user_id: int, method: str, status: str) -> None:
    """Count one successful authenticated request, bounded by the user label-set cap."""
    labels = (str(user_id), method, status)
    with _USER_LABEL_SETS_LOCK:
        _USER_LABEL_SETS[labels] = None
        _USER_LABEL_SETS.move_to_end(labels)
        USER_REQUESTS.labels(*labels).inc()
        while len(_USER_LABEL_SETS) > MAX_USER_LABEL_SETS:
            oldest, _ = _USER_LABEL_SETS.popitem(last=False)
            USER_REQUESTS.remove(*oldest)


#: Requests attributed to the league in the route's ``league_id`` path parameter. Routes without
#: that parameter (for example ``/api/v1/me/leagues``) contribute no series here.
LEAGUE_REQUESTS = Counter(
    "app_league_requests_total",
    "Requests attributed to the league in the request path, by numeric league id.",
    ("league_id", "method", "status"),
)

#: Upper bound on live league attribution label sets. Deleted leagues are removed eagerly, and
#: this cap is the backstop for a request already in flight when the league is deleted. It also
#: bounds an operator who keeps creating and deleting leagues.
MAX_LEAGUE_LABEL_SETS = 2048

#: Live label sets, oldest first, so the cap can evict the least recently used one.
_LEAGUE_LABEL_SETS: OrderedDict[tuple[str, str, str], None] = OrderedDict()
_LEAGUE_LABEL_SETS_LOCK = Lock()


def observe_league_request(league_id: int, method: str, status: str) -> None:
    """Count one successful league-scoped request, bounded by the label-set cap.

    The increment happens under the same lock as cleanup, so a concurrent :func:`forget_league`
    cannot leave a tracked label set without its counter child. A request that completes after
    its league is deleted can re-add one child, but the cap keeps the total series bounded.
    """
    labels = (str(league_id), method, status)
    with _LEAGUE_LABEL_SETS_LOCK:
        _LEAGUE_LABEL_SETS[labels] = None
        _LEAGUE_LABEL_SETS.move_to_end(labels)
        LEAGUE_REQUESTS.labels(*labels).inc()
        while len(_LEAGUE_LABEL_SETS) > MAX_LEAGUE_LABEL_SETS:
            oldest, _ = _LEAGUE_LABEL_SETS.popitem(last=False)
            LEAGUE_REQUESTS.remove(*oldest)


def forget_league(league_id: int) -> None:
    """Drop every attribution series for a deleted league.

    A labeled counter child is never garbage-collected, so without this a deleted league would
    keep appearing on every scrape and an admin could grow the registry by creating and deleting
    leagues. The total remains bounded by :data:`MAX_LEAGUE_LABEL_SETS` even if a request is
    already in flight when deletion commits.
    """
    prefix = str(league_id)
    with _LEAGUE_LABEL_SETS_LOCK:
        stale = [labels for labels in _LEAGUE_LABEL_SETS if labels[0] == prefix]
        for labels in stale:
            LEAGUE_REQUESTS.remove(*labels)
            del _LEAGUE_LABEL_SETS[labels]
