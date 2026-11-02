"""Unattended active-week projection refresh and its in-process cron schedule.

The refresh runs inside the API process so its Prometheus counters share the scrape target. It
uses an APScheduler :class:`~apscheduler.schedulers.background.BackgroundScheduler` with one job
whose ``OrTrigger`` fires every fifteen minutes on Sundays from 13:00 and Mondays from 20:00
(through 23:45) in the configured timezone. No request handler ever calls a provider for
projections; this job is the only writer of the projection table.

Credentials are the stored, encrypted ESPN cookies on league memberships. The job shuffles the
credential-holding memberships and tries them until one succeeds. An authentication failure moves
to the next holder; any other provider failure aborts the league for this run. Cookies and emails
are never logged or included in an exception.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.combining import OrTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.auth_repositories import MembershipRepository
from app.db.repositories import SyncRepository
from app.db.session import get_session_factory
from app.metrics import WEEK_REFRESH_TOTAL
from app.providers.base import LeagueRef, ProviderAuthError
from app.providers.espn.credentials import create_espn_provider
from app.security.crypto import CredentialCryptoError
from app.services.league_service import ProviderFactory
from app.services.sync_service import ActiveWeekSyncSummary, SyncService

#: The provider natural key used to resolve stored leagues.
DEFAULT_PROVIDER_ID = "espn"

#: The fixed windows. APScheduler evaluates them in the configured zone, including DST changes.
_WINDOW_TRIGGERS: tuple[tuple[str, str], ...] = (("sun", "13-23"), ("mon", "20-23"))

_LOG = logging.getLogger(__name__)

type RefreshStatus = Literal["ok", "no_active_week", "no_credentials", "auth_failed", "failed"]


@dataclass(frozen=True)
class LeagueRefreshResult:
    """One league's outcome in an active-week refresh run.

    ``status`` is a fixed code safe to log or display. ``summary`` is present only when a sync
    completed; an auth failure means every attempted holder was rejected, while ``failed`` covers a
    key/config fault or a provider error that credential rotation cannot fix.
    """

    league_id: int
    external_id: str
    status: RefreshStatus
    summary: ActiveWeekSyncSummary | None


@dataclass(frozen=True)
class _LeagueSpec:
    """A stored league's identity and latest season, copied out of the read session."""

    league_id: int
    external_id: str
    provider: str
    season: int


def build_trigger(timezone: ZoneInfo) -> OrTrigger:
    """Return the weekly projection-refresh trigger.

    One combined trigger keeps a single job, so APScheduler's ``max_instances=1`` prevents the
    Sunday and Monday windows from ever running concurrently.
    """
    return OrTrigger(
        [
            CronTrigger(
                day_of_week=day_of_week,
                hour=hours,
                minute="*/15",
                timezone=timezone,
            )
            for day_of_week, hours in _WINDOW_TRIGGERS
        ]
    )


def build_scheduler(*, job: Callable[[], None], timezone: ZoneInfo) -> BackgroundScheduler:
    """Return a started-less scheduler with the single refresh job registered.

    ``coalesce`` collapses missed runs into one, ``max_instances=1`` prevents overlap, and
    ``misfire_grace_time`` lets a briefly delayed run still execute. The job store is in memory:
    the refresh is idempotent and resumes at the next tick after a restart.
    """
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        job,
        trigger=build_trigger(timezone),
        id="projection-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    return scheduler


def start_projection_scheduler(settings: Settings) -> BackgroundScheduler | None:
    """Start the projection scheduler when enabled, or return None.

    Disabled by default so tests and local development never spawn a thread or call a provider.
    Production enables it in ``deploy/server/.env``.
    """
    if not settings.projection_refresh_enabled:
        return None
    try:
        timezone = ZoneInfo(settings.projection_refresh_timezone)
    except ZoneInfoNotFoundError as error:
        raise RuntimeError(
            "PROJECTION_REFRESH_TIMEZONE must name a timezone available to zoneinfo"
        ) from error
    scheduler = build_scheduler(job=refresh_active_weeks_job, timezone=timezone)
    scheduler.start()
    return scheduler


def parse_league_ids(value: str) -> tuple[str, ...] | None:
    """Parse a comma-separated external-id list; empty means every stored league."""
    ids = tuple(part.strip() for part in value.split(",") if part.strip())
    return ids or None


def refresh_active_weeks(
    *,
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory = create_espn_provider,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    league_external_ids: Sequence[str] | None = None,
    provider_id: str = DEFAULT_PROVIDER_ID,
    random_source: random.Random | None = None,
) -> list[LeagueRefreshResult]:
    """Refresh the active week for the configured leagues and return one result per league.

    A failure in one league never prevents the others from running. Credentials are shuffled with
    ``random_source`` (a ``SystemRandom`` by default) so no single member is always used; a
    ``ProviderAuthError`` advances to the next holder. ``CredentialCryptoError`` aborts that league
    because a key fault is not fixed by trying another membership.
    """
    rng = random_source or random.SystemRandom()
    with session_factory() as session:
        repository = SyncRepository(session)
        specs = _league_specs(repository, provider_id, league_external_ids)
        credentials_by_league = {
            spec.league_id: _credential_tokens(session, spec.league_id) for spec in specs
        }

    results: list[LeagueRefreshResult] = []
    for spec in specs:
        results.append(
            _refresh_league(
                spec=spec,
                credentials=credentials_by_league[spec.league_id],
                session_factory=session_factory,
                provider_factory=provider_factory,
                clock=clock,
                random_source=rng,
            )
        )
    return results


def _league_specs(
    repository: SyncRepository,
    provider_id: str,
    league_external_ids: Sequence[str] | None,
) -> list[_LeagueSpec]:
    """Return each in-scope league with its latest stored season.

    A league with no stored season is skipped: there is nothing to project.
    """
    if league_external_ids:
        leagues = [
            league
            for external_id in league_external_ids
            if (league := repository.get_league(provider_id, external_id)) is not None
        ]
    else:
        leagues = [league for league in repository.list_leagues() if league.provider == provider_id]

    specs: list[_LeagueSpec] = []
    for league in leagues:
        seasons = repository.list_league_seasons(league.id)
        if not seasons:
            continue
        specs.append(
            _LeagueSpec(
                league_id=league.id,
                external_id=league.external_id,
                provider=league.provider,
                season=max(row.season for row in seasons),
            )
        )
    return specs


def _credential_tokens(session: Session, league_id: int) -> list[tuple[str, str]]:
    """Return the league's encrypted credential pairs without decrypting or logging them."""
    tokens: list[tuple[str, str]] = []
    for membership in MembershipRepository(session).list_with_credentials(league_id):
        if membership.espn_s2_encrypted and membership.espn_swid_encrypted:
            tokens.append((membership.espn_s2_encrypted, membership.espn_swid_encrypted))
    return tokens


def _refresh_league(
    *,
    spec: _LeagueSpec,
    credentials: Sequence[tuple[str, str]],
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory,
    clock: Callable[[], datetime],
    random_source: random.Random,
) -> LeagueRefreshResult:
    """Try credential holders in a shuffled order until one completes the active-week sync."""
    if not credentials:
        WEEK_REFRESH_TOTAL.labels("projection", "no_credentials").inc()
        return LeagueRefreshResult(spec.league_id, spec.external_id, "no_credentials", None)

    holders = list(credentials)
    random_source.shuffle(holders)
    for espn_s2_encrypted, espn_swid_encrypted in holders:
        try:
            with session_factory() as session:
                provider = provider_factory(
                    espn_s2_encrypted=espn_s2_encrypted,
                    espn_swid_encrypted=espn_swid_encrypted,
                )
                summary = SyncService(provider, session, clock=clock).sync_active_week(
                    LeagueRef(external_id=spec.external_id), spec.provider, spec.season
                )
                session.commit()
            status: RefreshStatus = "ok" if summary.active_week is not None else "no_active_week"
            return LeagueRefreshResult(spec.league_id, spec.external_id, status, summary)
        except ProviderAuthError:
            WEEK_REFRESH_TOTAL.labels("projection", "auth_failed").inc()
            continue
        except CredentialCryptoError:
            WEEK_REFRESH_TOTAL.labels("projection", "failed").inc()
            _LOG.warning("projection refresh failed: credential decryption error")
            return LeagueRefreshResult(spec.league_id, spec.external_id, "failed", None)
        except Exception:
            WEEK_REFRESH_TOTAL.labels("projection", "failed").inc()
            _LOG.warning("projection refresh failed")
            return LeagueRefreshResult(spec.league_id, spec.external_id, "failed", None)

    WEEK_REFRESH_TOTAL.labels("projection", "auth_failed").inc()
    return LeagueRefreshResult(spec.league_id, spec.external_id, "auth_failed", None)


def refresh_active_weeks_job() -> None:
    """APScheduler entrypoint: run the refresh with production settings.

    Any exception is contained so a failed run can never take the API process down; the Prometheus
    counters and the process log are the operational signal.
    """
    settings = get_settings()
    try:
        refresh_active_weeks(
            session_factory=get_session_factory(),
            provider_factory=create_espn_provider,
            clock=lambda: datetime.now(UTC),
            league_external_ids=parse_league_ids(settings.projection_refresh_leagues),
        )
    except Exception:  # a scheduler job must never escape into the scheduler thread
        _LOG.warning("active-week projection refresh failed")
