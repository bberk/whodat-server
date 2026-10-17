"""Command-line entry point (sync, recompute, create-user).

The subcommands are wired up but do not do work yet; the sync and user commands are implemented
in later milestones (M3/M4). `python -m app.cli --help` lists the available commands.
"""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the sync, recompute, and create-user subcommands."""
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="sync a league season from the provider")
    sync.add_argument("--league", required=True, help="league id")
    sync.add_argument("--season", type=int, required=True, help="season year")
    sync.add_argument("--weeks", help="week range to sync, e.g. 1-5")

    recompute = sub.add_parser("recompute", help="recompute VP without provider calls")
    recompute.add_argument("--league", required=True, help="league id")
    recompute.add_argument("--season", type=int, required=True, help="season year")

    sub.add_parser("create-user", help="create an application user")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and return a process exit code."""
    build_parser().parse_args(argv)
    print("not implemented yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
