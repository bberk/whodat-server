import runpy

import pytest

from app.cli import build_parser, main


def test_cli_sync_parses_and_returns_zero() -> None:
    assert main(["sync", "--league", "1", "--season", "2026"]) == 0


def test_cli_recompute_parses_and_returns_zero() -> None:
    assert main(["recompute", "--league", "1", "--season", "2026"]) == 0


def test_cli_create_user_parses_and_returns_zero() -> None:
    assert main(["create-user"]) == 0


def test_cli_parser_requires_a_subcommand() -> None:
    parser = build_parser()
    assert parser.prog == "python -m app.cli"


def test_cli_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m app.cli` returns exit code 0 via SystemExit."""
    monkeypatch.setattr("sys.argv", ["app.cli", "create-user"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("app.cli", run_name="__main__")
    assert excinfo.value.code == 0
