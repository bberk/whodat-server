from sqlalchemy import JSON, Numeric, UniqueConstraint
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.db.models import AppUser, League, Matchup, Owner, Score, Team


def test_AC_DB_01_schema_defines_normalized_league_entities() -> None:
    """The schema contains each league, owner, team, matchup, score, and user entity."""
    expected = {"league", "owner", "team", "matchup", "score", "app_user"}
    assert {
        model.__tablename__ for model in (League, Owner, Team, Matchup, Score, AppUser)
    } == expected

    assert {column.name for column in League.__table__.columns} >= {
        "provider",
        "external_id",
        "name",
        "metadata",
        "provider_config_ref",
    }
    assert {column.name for column in Owner.__table__.columns} >= {
        "league_id",
        "external_id",
        "display_name",
    }
    assert {column.name for column in Team.__table__.columns} >= {
        "league_id",
        "season",
        "external_id",
        "name",
        "division",
        "owner_id",
    }
    assert {column.name for column in Matchup.__table__.columns} >= {
        "league_id",
        "season",
        "week",
        "home_team_id",
        "away_team_id",
        "is_playoff",
        "is_complete",
    }
    assert {column.name for column in Score.__table__.columns} >= {
        "team_id",
        "league_id",
        "season",
        "week",
        "points",
        "victory_points",
    }


def test_AC_DB_04_score_persists_total_and_each_vp_component() -> None:
    """Score uses the specified precision for points, total VP, and all components."""
    columns = Score.__table__.c
    assert isinstance(League.__table__.c.metadata.type, JSON)
    assert isinstance(columns.points.type, Numeric)
    assert (columns.points.type.precision, columns.points.type.scale) == (8, 2)

    for name in ("victory_points", "vp_h2h", "vp_top_half", "vp_high", "vp_low"):
        column_type = columns[name].type
        assert isinstance(column_type, Numeric)
        assert (column_type.precision, column_type.scale) == (10, 6)


def test_AC_DB_05_schema_ddl_compiles_for_sqlite_and_postgresql() -> None:
    """All table DDL uses types supported by both configured database engines."""
    for model in (League, Owner, Team, Matchup, Score, AppUser):
        table = model.__table__
        sqlite_ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
        postgres_ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert table.name in sqlite_ddl
        assert table.name in postgres_ddl


def test_schema_natural_keys_and_foreign_keys_match_contract() -> None:
    """The schema enforces the declared natural keys and entity references."""
    expected_unique_keys = {
        "league": {("provider", "external_id")},
        "owner": {("league_id", "external_id")},
        "team": {("league_id", "season", "external_id")},
        "matchup": {("league_id", "season", "week", "home_team_id")},
        "score": {("team_id", "season", "week")},
        "app_user": {("email",)},
    }
    models = (League, Owner, Team, Matchup, Score, AppUser)
    for model in models:
        unique_keys = {
            tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert unique_keys == expected_unique_keys[model.__tablename__]

    expected_foreign_keys = {
        "owner": {("league_id", "league.id")},
        "team": {("league_id", "league.id"), ("owner_id", "owner.id")},
        "matchup": {
            ("league_id", "league.id"),
            ("home_team_id", "team.id"),
            ("away_team_id", "team.id"),
        },
        "score": {("team_id", "team.id"), ("league_id", "league.id")},
        "app_user": {("owner_id", "owner.id")},
        "league": set(),
    }
    for model in models:
        actual = {
            (foreign_key.parent.name, foreign_key.target_fullname)
            for foreign_key in model.__table__.foreign_keys
        }
        assert actual == expected_foreign_keys[model.__tablename__]
