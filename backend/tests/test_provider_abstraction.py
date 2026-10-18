"""Tests for the provider contract, registry, and in-memory fake provider."""

import ast
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from app.providers.base import (
    LeagueDTO,
    LeagueRef,
    MatchupDTO,
    MatchupSideDTO,
    OwnerDTO,
    TeamDTO,
    WeekStatus,
)
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry

type LeagueKey = tuple[str, int]
type FakeSeed = tuple[
    LeagueDTO,
    list[OwnerDTO],
    list[TeamDTO],
    dict[int, list[MatchupDTO]],
    WeekStatus,
]

LEAGUE_REF = LeagueRef(external_id="league-1")
SEASON = 2025


def _seed() -> tuple[dict[LeagueKey, FakeSeed], list[OwnerDTO], list[TeamDTO]]:
    owners = [OwnerDTO(external_id="owner-1", display_name="Owner One")]
    teams = [
        TeamDTO(
            external_id="team-1",
            name="Team One",
            division="East",
            owner_external_id="owner-1",
        )
    ]
    matchups = [
        MatchupDTO(
            week=1,
            home=MatchupSideDTO(team_external_id="team-1", points=Decimal("123.40")),
            away=None,
            is_playoff=False,
            is_complete=True,
        )
    ]
    seed: FakeSeed = (
        LeagueDTO(external_id="league-1", name="League One", metadata={"teams": 1}),
        owners,
        teams,
        {1: matchups},
        WeekStatus(last_completed_week=1),
    )
    return {("league-1", SEASON): seed}, owners, teams


def test_AC_PR_01_provider_contract_exposes_normalized_exact_values() -> None:
    matchup = MatchupDTO(
        week=2,
        home=MatchupSideDTO(team_external_id="home", points=Decimal("123.40")),
        away=MatchupSideDTO(team_external_id="away", points=Decimal("98.75")),
        is_playoff=False,
        is_complete=True,
    )

    assert matchup.home.points == Decimal("123.40")
    assert matchup.away is not None
    assert matchup.away.points == Decimal("98.75")
    assert WeekStatus(last_completed_week=None).last_completed_week is None


def test_AC_PR_04_fake_provider_is_registered_only_through_registry() -> None:
    seed, _, _ = _seed()
    provider = FakeProvider(seed)
    registry = ProviderRegistry()

    registry.register(provider)

    assert registry.get("fake") is provider


def test_registry_rejects_duplicate_provider_ids_without_replacing() -> None:
    seed, _, _ = _seed()
    provider = FakeProvider(seed)
    registry = ProviderRegistry()
    registry.register(provider)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider)

    assert registry.get("fake") is provider


def test_registry_rejects_a_different_provider_with_duplicate_id() -> None:
    seed, _, _ = _seed()
    first = FakeProvider(seed)
    second = FakeProvider(seed)
    registry = ProviderRegistry()
    registry.register(first)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(second)

    assert registry.get("fake") is first


def test_registry_raises_key_error_for_unknown_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(KeyError):
        registry.get("unknown")


def test_fake_provider_returns_normalized_seeded_data() -> None:
    seed, _, _ = _seed()
    provider = FakeProvider(seed)

    assert provider.fetch_league(LEAGUE_REF, SEASON).name == "League One"
    assert provider.fetch_owners(LEAGUE_REF, SEASON) == [
        OwnerDTO(external_id="owner-1", display_name="Owner One")
    ]
    assert provider.fetch_teams(LEAGUE_REF, SEASON)[0].division == "East"
    assert provider.fetch_matchups(LEAGUE_REF, SEASON, 1)[0].home.points == Decimal("123.40")
    assert provider.current_week(LEAGUE_REF, SEASON) == WeekStatus(last_completed_week=1)


def test_fake_provider_snapshots_input_sequences_and_returns_fresh_lists() -> None:
    seed, owners, teams = _seed()
    provider = FakeProvider(seed)
    owners.clear()
    teams.clear()
    seed[("league-1", SEASON)][3][1].clear()

    returned_owners = provider.fetch_owners(LEAGUE_REF, SEASON)
    returned_teams = provider.fetch_teams(LEAGUE_REF, SEASON)
    returned_matchups = provider.fetch_matchups(LEAGUE_REF, SEASON, 1)
    returned_owners.clear()
    returned_teams.clear()
    returned_matchups.clear()

    assert provider.fetch_owners(LEAGUE_REF, SEASON)
    assert provider.fetch_teams(LEAGUE_REF, SEASON)
    assert provider.fetch_matchups(LEAGUE_REF, SEASON, 1)


@pytest.mark.parametrize(
    "lookup",
    [
        lambda provider: provider.fetch_league(LeagueRef("missing"), SEASON),
        lambda provider: provider.fetch_owners(LeagueRef("missing"), SEASON),
        lambda provider: provider.fetch_teams(LeagueRef("missing"), SEASON),
        lambda provider: provider.fetch_matchups(LeagueRef("missing"), SEASON, 1),
        lambda provider: provider.current_week(LeagueRef("missing"), SEASON),
        lambda provider: provider.fetch_league(LEAGUE_REF, SEASON + 1),
    ],
)
def test_fake_provider_raises_key_error_for_unknown_league_or_season(
    lookup: Callable[[FakeProvider], object],
) -> None:
    seed, _, _ = _seed()
    provider = FakeProvider(seed)

    with pytest.raises(KeyError):
        lookup(provider)


def test_fake_provider_raises_key_error_for_unknown_week() -> None:
    seed, _, _ = _seed()
    provider = FakeProvider(seed)

    with pytest.raises(KeyError):
        provider.fetch_matchups(LEAGUE_REF, SEASON, 2)


def test_AC_PR_03_espn_api_imports_are_confined_to_espn_provider() -> None:
    app_root = Path(__file__).parents[1] / "src" / "app"
    espn_root = app_root / "providers" / "espn"
    violations: list[str] = []

    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_espn_api = any(
            (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "espn_api" or alias.name.startswith("espn_api.")
                    for alias in node.names
                )
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "espn_api" or node.module.startswith("espn_api."))
            )
            for node in ast.walk(tree)
        )
        if imports_espn_api and not path.is_relative_to(espn_root):
            violations.append(str(path.relative_to(app_root)))

    assert violations == []


def test_provider_contract_modules_do_not_import_domain_internals() -> None:
    provider_root = Path(__file__).parents[1] / "src" / "app" / "providers"
    violations: list[str] = []

    for filename in ("base.py", "fake.py"):
        path = provider_root / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_domain = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("app.domain") for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "app.domain" or node.module.startswith("app.domain."))
            )
            for node in ast.walk(tree)
        )
        if imports_domain:
            violations.append(filename)

    assert violations == []
