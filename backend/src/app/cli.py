"""Command-line entry point (sync, recompute, create-user).

``sync`` fetches a league season through the configured provider (ESPN in production) and writes
normalized leagues, owners, teams, matchups, scores, and weekly Victory Points. ``recompute``
rebuilds Victory Points from data already stored, without any provider calls. ``create-user``
remains a stub for the M4 auth work.

Both real commands own their database transaction: they open a session, run the service, and
commit. Tests inject a ``ProviderRegistry`` (for example holding a ``FakeProvider``) and a
session factory bound to a throwaway database through :func:`main`'s keyword arguments, so no
test touches ESPN or the configured development database.
"""

import argparse
import re
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_session_factory
from app.providers.base import LeagueRef
from app.providers.espn.adapter import ESPNLeagueProvider
from app.providers.registry import ProviderRegistry
from app.services.sync_service import SyncError, SyncService

# Production sync always reads through the ESPN provider registered by build_provider_registry.
DEFAULT_PROVIDER_ID = "espn"

_WEEK_RANGE = re.compile(r"^(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$")


def parse_week_range(value: str) -> list[int]:
    """Parse a 1-based week or inclusive week range such as ``"3"`` or ``"1-5"``.

    The result is always a non-empty ascending list of positive week numbers. Anything else
    (zero, a reversed range, or stray characters) raises ``argparse.ArgumentTypeError``, which
    argparse turns into a structured usage error on exit code 2.
    """
    match = _WEEK_RANGE.match(value.strip())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"expected a positive week or range like '1-5', got {value!r}"
        )
    start = int(match.group("start"))
    end = int(match.group("end")) if match.group("end") else start
    if start > end:
        raise argparse.ArgumentTypeError(f"week range start must not exceed its end, got {value!r}")
    return list(range(start, end + 1))


def build_provider_registry() -> ProviderRegistry:
    """Return the production provider registry with the ESPN adapter registered.

    Building the registry only constructs the adapter; it makes no network calls. Credentials are
    read lazily from the provider-local environment settings on first use and are never stored in
    DTOs or the database.
    """
    registry = ProviderRegistry()
    registry.register(ESPNLeagueProvider())
    return registry


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the sync, recompute, and create-user subcommands."""
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="sync a league season from the provider")
    sync.add_argument("--league", required=True, help="league external id")
    sync.add_argument("--season", type=int, required=True, help="season year")
    sync.add_argument(
        "--weeks",
        type=parse_week_range,
        metavar="START-END",
        help="inclusive week range to sync, e.g. 1-5 (default: every completed week)",
    )

    recompute = sub.add_parser("recompute", help="recompute VP without provider calls")
    recompute.add_argument("--league", required=True, help="league external id")
    recompute.add_argument("--season", type=int, required=True, help="season year")

    sub.add_parser("create-user", help="create an application user")

    return parser


def _format_weeks(weeks: Sequence[int]) -> str:
    """Render a week sequence as ``1,2,3`` or ``-`` when it is empty."""
    return ",".join(str(week) for week in weeks) if weeks else "-"


def _run_sync(
    args: argparse.Namespace,
    registry: ProviderRegistry,
    session_factory: sessionmaker[Session],
    provider_id: str,
) -> int:
    """Run ``sync`` and return a process exit code, reporting failures on stderr."""
    try:
        provider = registry.get(provider_id)
    except KeyError:
        print(f"error: no provider registered for {provider_id!r}", file=sys.stderr)
        return 1

    try:
        league_ref = LeagueRef(external_id=args.league)
        with session_factory() as session:
            summary = SyncService(provider, session).sync_league(
                league_ref, provider_id, args.season, weeks=args.weeks
            )
            session.commit()
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"sync: league={summary.league_id} season={summary.season} "
        f"weeks_synced={_format_weeks(summary.weeks_synced)} "
        f"weeks_with_vp_recomputed={_format_weeks(summary.weeks_with_vp_recomputed)} "
        f"league_changed={str(summary.league_changed).lower()} "
        f"owners_changed={summary.owners_changed} teams_changed={summary.teams_changed}"
    )
    return 0


def _run_recompute(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    provider_id: str,
) -> int:
    """Run ``recompute`` and return a process exit code, reporting failures on stderr.

    No provider is bound or consulted: the stored league, matchups, and scores are the only
    inputs, together with the same pure VP engine that sync uses.
    """
    try:
        league_ref = LeagueRef(external_id=args.league)
        with session_factory() as session:
            summary = SyncService(None, session).recompute_league(
                league_ref, provider_id, args.season
            )
            session.commit()
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"recompute: league={summary.league_id} season={summary.season} "
        f"regular_season_length={summary.regular_season_length} "
        f"weeks_recomputed={_format_weeks(summary.weeks_recomputed)} "
        f"weeks_skipped={_format_weeks(summary.weeks_skipped)}"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: ProviderRegistry | None = None,
    session_factory: sessionmaker[Session] | None = None,
    provider_id: str = DEFAULT_PROVIDER_ID,
) -> int:
    """Parse arguments, run the requested command, and return a process exit code.

    ``registry`` and ``session_factory`` are dependency-injection seams: production callers leave
    them unset and get the ESPN registry plus the configured database, while tests pass a registry
    holding a ``FakeProvider`` and a factory bound to an isolated SQLite database.
    """
    args = build_parser().parse_args(argv)

    if args.command == "create-user":
        # Auth arrives in M4; keep the documented stub until then.
        print("not implemented yet")
        return 0

    factory = session_factory if session_factory is not None else get_session_factory()

    if args.command == "sync":
        active_registry = registry if registry is not None else build_provider_registry()
        return _run_sync(args, active_registry, factory, provider_id)

    if args.command == "recompute":
        return _run_recompute(args, factory, provider_id)

    raise AssertionError(f"unhandled command: {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
