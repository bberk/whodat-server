"""Command-line entry point (sync, recompute, create-invite, create-user).

``sync`` fetches a league season through the ESPN provider and writes normalized leagues, owners,
teams, matchups, scores, and weekly Victory Points. It requires ``--as-email`` and uses only that
member's stored, encrypted league credentials; there is no environment credential path and no
fallback to another member. ``recompute`` rebuilds Victory Points from data already stored, without
any provider calls. ``create-invite`` mints an invite and prints its raw code once; only the code
hash is stored. A member invite names its league, while an admin invite may be league-less so the
first account can be created before any league exists. ``create-user`` remains a stub for the M4
auth work.

Every real command owns its database transaction: it opens a session, runs the service or
repository calls, and commits. Tests inject a provider factory (for example returning a
``FakeProvider`` after checking the decrypted cookies), a session factory bound to a throwaway
database, and a clock through :func:`main`'s keyword arguments, so no test touches ESPN, the
network, or the configured development database.
"""

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.db.auth_repositories import InviteRepository, MembershipRepository, UserRepository
from app.db.models import ROLE_ADMIN, ROLE_MEMBER, VALID_ROLES
from app.db.repositories import SyncRepository
from app.db.session import get_session_factory
from app.providers.base import LeagueRef
from app.providers.espn.credentials import create_espn_provider
from app.security.crypto import CredentialCryptoError
from app.security.invite_codes import generate_invite_code, hash_invite_code
from app.services.league_service import ProviderFactory
from app.services.sync_service import SyncError, SyncService

# The provider natural key used for stored leagues and the sync rows.
DEFAULT_PROVIDER_ID = "espn"

# The documented default invite lifetime (AC-AU-01).
DEFAULT_INVITE_LIFETIME = timedelta(days=7)

# A decade is far beyond any real invite lifetime and keeps expiry arithmetic away from the
# timedelta/datetime range limits, so an absurd argument becomes a usage error, not a traceback.
_MAX_INVITE_LIFETIME_DAYS = 3650

_WEEK_RANGE = re.compile(r"^(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$")
_DURATION = re.compile(r"^(?P<amount>[0-9]+)(?P<unit>[dh])?$")

# Defensive ceiling for a fantasy football season (regular season plus playoffs). No provider
# reports anything close to this, so it only rejects absurd ranges without silently truncating.
_MAX_WEEK = 30


def parse_week_range(value: str) -> list[int]:
    """Parse a 1-based week or inclusive week range such as ``"3"`` or ``"1-5"``.

    The result is always a non-empty ascending list of positive week numbers no greater than
    ``_MAX_WEEK``. Anything else (zero, a reversed or over-long range, or stray characters) raises
    ``argparse.ArgumentTypeError``, which argparse turns into a structured usage error on exit code
    2. Bounding the end keeps a typo such as ``--weeks 1-1000000`` from materializing a huge list.
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
    if end > _MAX_WEEK:
        raise argparse.ArgumentTypeError(
            f"week {end} is beyond the supported maximum of {_MAX_WEEK}, got {value!r}"
        )
    return list(range(start, end + 1))


def parse_expiry_duration(value: str) -> timedelta:
    """Parse an invite lifetime such as ``7d``, ``24h``, or a bare integer meaning days.

    A duration must be a positive whole number of days or hours, no longer than 3650 days. A bare
    integer is read as days, which matches the documented ``--expires 7`` shorthand. Anything else
    (zero, a negative or fractional number, an unsupported unit, an out-of-range value, or stray
    characters) raises ``argparse.ArgumentTypeError``, which argparse reports as a usage error on
    exit code 2 instead of letting a traceback escape. The range check happens before constructing
    the timedelta so even an enormous value cannot raise ``OverflowError``.
    """
    match = _DURATION.match(value.strip())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"expected a positive duration like '7d' or '24h', got {value!r}"
        )
    amount = int(match.group("amount"))
    if amount <= 0:
        raise argparse.ArgumentTypeError(f"duration must be positive, got {value!r}")
    unit = match.group("unit") or "d"
    max_amount = _MAX_INVITE_LIFETIME_DAYS * 24 if unit == "h" else _MAX_INVITE_LIFETIME_DAYS
    if amount > max_amount:
        raise argparse.ArgumentTypeError(
            f"duration must not exceed {_MAX_INVITE_LIFETIME_DAYS} days, got {value!r}"
        )
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def parse_role(value: str) -> str:
    """Return a supported invite role, raising an argparse usage error for anything else."""
    if value not in VALID_ROLES:
        raise argparse.ArgumentTypeError(
            f"invalid role {value!r}; expected one of {sorted(VALID_ROLES)}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with sync, recompute, create-invite, and create-user commands."""
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="sync a league season from the provider")
    sync.add_argument("--league", required=True, help="league external id")
    sync.add_argument("--season", type=int, required=True, help="season year")
    sync.add_argument(
        "--as-email",
        required=True,
        metavar="EMAIL",
        help="email of the member whose stored league credentials are used",
    )
    sync.add_argument(
        "--weeks",
        type=parse_week_range,
        metavar="START-END",
        help="inclusive week range to sync, e.g. 1-5 (default: every completed week)",
    )

    recompute = sub.add_parser("recompute", help="recompute VP without provider calls")
    recompute.add_argument("--league", required=True, help="league external id")
    recompute.add_argument("--season", type=int, required=True, help="season year")

    create_invite = sub.add_parser("create-invite", help="create an invite code")
    create_invite.add_argument(
        "--league",
        help="league external id (required for --role member; rejected for --role admin)",
    )
    create_invite.add_argument(
        "--role", required=True, type=parse_role, help="role granted by the invite: admin or member"
    )
    create_invite.add_argument(
        "--expires",
        type=parse_expiry_duration,
        default=DEFAULT_INVITE_LIFETIME,
        metavar="DURATION",
        help="invite lifetime like 7d or 24h (default: 7d)",
    )
    create_invite.add_argument(
        "--provider", default=DEFAULT_PROVIDER_ID, help="provider id (default: espn)"
    )

    sub.add_parser("create-user", help="create an application user")

    return parser


def _validate_create_invite_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Enforce which roles may carry a league, reporting violations as usage errors.

    Member access is always scoped to a league, while admin access may be granted before any league
    exists. Both violations exit with code 2 before a database session is opened, so a rejected
    invocation never writes an invite row.
    """
    if args.role == ROLE_MEMBER and args.league is None:
        parser.error("create-invite --role member requires --league")
    if args.role == ROLE_ADMIN and args.league is not None:
        parser.error("create-invite --role admin does not accept --league")


def _format_weeks(weeks: Sequence[int]) -> str:
    """Render a week sequence as ``1,2,3`` or ``-`` when it is empty."""
    return ",".join(str(week) for week in weeks) if weeks else "-"


def _run_sync(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    provider_id: str,
    provider_factory: ProviderFactory,
) -> int:
    """Run ``sync`` with one member's stored credentials and return a process exit code.

    The member is selected explicitly with ``--as-email``. Their membership in the stored league
    must hold both encrypted ESPN cookies; the provider factory decrypts them behind the provider
    boundary and builds the adapter. There is no environment credential path and no fallback to
    another member's credentials. Every expected failure prints a fixed error code and message on
    stderr and exits 1 without exposing cookie values or ciphertext.
    """
    with session_factory() as session:
        try:
            user = UserRepository(session).get_by_email(args.as_email)
        except ValueError:
            user = None
        if user is None:
            print(
                f"error: user_not_found: no account exists for {args.as_email!r}",
                file=sys.stderr,
            )
            return 1

        league = SyncRepository(session).get_league(provider_id, args.league)
        if league is None:
            print(
                f"error: league_not_found: no league stored for provider {provider_id!r} "
                f"with external id {args.league!r}",
                file=sys.stderr,
            )
            return 1

        membership = MembershipRepository(session).get(user.id, league.id)
        if membership is None:
            print(
                f"error: not_a_member: {args.as_email!r} is not a member of league {args.league!r}",
                file=sys.stderr,
            )
            return 1

        espn_s2_encrypted = membership.espn_s2_encrypted
        espn_swid_encrypted = membership.espn_swid_encrypted
        if not espn_s2_encrypted or not espn_swid_encrypted:
            print(
                f"error: credentials_missing: the membership for {args.as_email!r} in league "
                f"{args.league!r} has no stored ESPN credentials",
                file=sys.stderr,
            )
            return 1

        try:
            provider = provider_factory(
                espn_s2_encrypted=espn_s2_encrypted,
                espn_swid_encrypted=espn_swid_encrypted,
            )
        except CredentialCryptoError:
            print(
                "error: credentials_unavailable: stored league credentials could not be decrypted",
                file=sys.stderr,
            )
            return 1

        try:
            summary = SyncService(provider, session).sync_league(
                LeagueRef(external_id=args.league),
                provider_id,
                args.season,
                weeks=args.weeks,
            )
            session.commit()
        except SyncError as error:
            print(f"error: sync_failed: {error}", file=sys.stderr)
            return 1
        except Exception:
            print("error: sync_failed: league data could not be synced", file=sys.stderr)
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


def _utc_now() -> datetime:
    """Return the current UTC wall-clock time (the production invite clock)."""
    return datetime.now(UTC)


def _run_create_invite(
    args: argparse.Namespace,
    session_factory: sessionmaker[Session],
    clock: Callable[[], datetime],
) -> int:
    """Run ``create-invite`` and return a process exit code.

    A member invite resolves its league by natural key through the repository layer; an admin
    invite is stored without a league and skips that lookup. No provider call or network access
    happens here. The raw code is printed only after the invite row commits: a failure returns a
    message on stderr without ever exposing an unpersisted or unprintable code.
    """
    with session_factory() as session:
        league_id: int | None = None
        if args.league is not None:
            league = SyncRepository(session).get_league(args.provider, args.league)
            if league is None:
                print(
                    f"error: no league stored for provider {args.provider!r} "
                    f"with external id {args.league!r}",
                    file=sys.stderr,
                )
                return 1
            league_id = league.id
        raw_code = generate_invite_code()
        InviteRepository(session).create(
            league_id,
            hash_invite_code(raw_code),
            clock() + args.expires,
            role=args.role,
        )
        session.commit()

    print(raw_code)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory = create_espn_provider,
    session_factory: sessionmaker[Session] | None = None,
    provider_id: str = DEFAULT_PROVIDER_ID,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Parse arguments, run the requested command, and return a process exit code.

    ``provider_factory``, ``session_factory``, and ``clock`` are dependency-injection seams:
    production callers leave them unset and get the ESPN credential factory (decryption stays
    behind the provider boundary), the configured database, and the real UTC clock, while tests
    pass a fake provider factory, a factory bound to an isolated SQLite database, and a fixed
    clock.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "create-invite":
        _validate_create_invite_args(args, parser)

    if args.command == "create-user":
        # Auth arrives in M4; keep the documented stub until then.
        print("not implemented yet")
        return 0

    factory = session_factory if session_factory is not None else get_session_factory()

    if args.command == "sync":
        return _run_sync(args, factory, provider_id, provider_factory)

    if args.command == "recompute":
        return _run_recompute(args, factory, provider_id)

    if args.command == "create-invite":
        return _run_create_invite(args, factory, clock or _utc_now)

    raise AssertionError(f"unhandled command: {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
