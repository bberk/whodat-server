"""The single model-metadata schema contract test (AC-DB-01, AC-DB-04).

Columns, natural keys, foreign keys, indexes, and the numeric/JSON precision of the Score and
league-season columns are asserted once here against SQLAlchemy metadata. Migrated DDL is asserted
in test_migrations.py, and repository behaviour lives in test_repositories.py and
test_auth_schema.py, so neither repeats these shapes.
"""

from sqlalchemy import JSON, Index, Numeric, Text, UniqueConstraint

from app.db.models import (
    AppUser,
    Invite,
    League,
    LeagueSeason,
    Matchup,
    Owner,
    Score,
    Team,
    UserLeague,
)

MODELS = (League, LeagueSeason, Owner, Team, Matchup, Score, AppUser, Invite, UserLeague)

EXPECTED_COLUMNS = {
    "league": {
        "id",
        "provider",
        "external_id",
        "name",
        "metadata",
        "provider_config_ref",
        "created_at",
        "updated_at",
    },
    "league_season": {"id", "league_id", "season", "metadata", "created_at", "updated_at"},
    "owner": {"id", "league_id", "external_id", "display_name", "created_at", "updated_at"},
    "team": {
        "id",
        "league_id",
        "season",
        "external_id",
        "name",
        "division",
        "owner_id",
        "created_at",
        "updated_at",
    },
    "matchup": {
        "id",
        "league_id",
        "season",
        "week",
        "home_team_id",
        "away_team_id",
        "is_playoff",
        "is_complete",
        "created_at",
        "updated_at",
    },
    "score": {
        "id",
        "team_id",
        "league_id",
        "season",
        "week",
        "points",
        "victory_points",
        "vp_h2h",
        "vp_top_half",
        "vp_high",
        "vp_low",
        "created_at",
        "updated_at",
    },
    "app_user": {"id", "email", "password_hash", "role", "created_at", "updated_at"},
    "invite": {
        "id",
        "league_id",
        "code_hash",
        "role",
        "expires_at",
        "created_at",
        "updated_at",
    },
    "user_league": {
        "id",
        "user_id",
        "league_id",
        "owner_id",
        "espn_s2_encrypted",
        "espn_swid_encrypted",
        "created_at",
        "updated_at",
    },
}

EXPECTED_UNIQUE_KEYS = {
    "league": {("uq_league_provider_external_id", ("provider", "external_id"))},
    "league_season": {("uq_league_season_league_season", ("league_id", "season"))},
    "owner": {("uq_owner_league_external_id", ("league_id", "external_id"))},
    "team": {("uq_team_league_season_external_id", ("league_id", "season", "external_id"))},
    "matchup": {
        ("uq_matchup_league_season_week_home", ("league_id", "season", "week", "home_team_id"))
    },
    "score": {("uq_score_team_season_week", ("team_id", "season", "week"))},
    "app_user": {("uq_app_user_email", ("email",))},
    "invite": {("uq_invite_code_hash", ("code_hash",))},
    "user_league": {("uq_user_league_user_id_league_id", ("user_id", "league_id"))},
}

EXPECTED_FOREIGN_KEYS = {
    "league": set(),
    "league_season": {("fk_league_season_league_id_league", ("league_id", "league.id"))},
    "owner": {("fk_owner_league_id_league", ("league_id", "league.id"))},
    "team": {
        ("fk_team_league_id_league", ("league_id", "league.id")),
        ("fk_team_owner_id_owner", ("owner_id", "owner.id")),
    },
    "matchup": {
        ("fk_matchup_league_id_league", ("league_id", "league.id")),
        ("fk_matchup_home_team_id_team", ("home_team_id", "team.id")),
        ("fk_matchup_away_team_id_team", ("away_team_id", "team.id")),
    },
    "score": {
        ("fk_score_team_id_team", ("team_id", "team.id")),
        ("fk_score_league_id_league", ("league_id", "league.id")),
    },
    "app_user": set(),
    "invite": {("fk_invite_league_id_league", ("league_id", "league.id"))},
    "user_league": {
        ("fk_user_league_user_id_app_user", ("user_id", "app_user.id")),
        ("fk_user_league_league_id_league", ("league_id", "league.id")),
        ("fk_user_league_owner_id_owner", ("owner_id", "owner.id")),
    },
}

EXPECTED_INDEXES = {
    "league": set(),
    "league_season": set(),
    "owner": set(),
    "team": set(),
    "matchup": set(),
    "score": set(),
    "app_user": set(),
    "invite": {("ix_invite_league_id", ("league_id",))},
    "user_league": {("ix_user_league_league_id", ("league_id",))},
}


def test_AC_DB_01_model_metadata_matches_the_schema_contract() -> None:
    """Every table exposes exactly its contracted columns, keys, indexes, and value types."""
    assert {model.__tablename__ for model in MODELS} == set(EXPECTED_COLUMNS)

    for model in MODELS:
        table = model.__table__
        name = model.__tablename__
        column_names = {column.name for column in table.columns}
        assert column_names == EXPECTED_COLUMNS[name], name

        unique_keys = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert unique_keys == EXPECTED_UNIQUE_KEYS[name], name

        foreign_keys = {
            (foreign_key.name, (foreign_key.parent.name, foreign_key.target_fullname))
            for foreign_key in table.foreign_keys
        }
        assert foreign_keys == EXPECTED_FOREIGN_KEYS[name], name

        indexes = {
            (index.name, tuple(column.name for column in index.columns))
            for index in table.indexes
            if isinstance(index, Index)
        }
        assert indexes == EXPECTED_INDEXES[name], name

    # AC-DB-04: Score stores points and every VP component at the declared precision.
    score_columns = Score.__table__.c
    assert isinstance(League.__table__.c.metadata.type, JSON)
    assert isinstance(score_columns.points.type, Numeric)
    assert (score_columns.points.type.precision, score_columns.points.type.scale) == (8, 2)
    for component in ("victory_points", "vp_h2h", "vp_top_half", "vp_high", "vp_low"):
        component_type = score_columns[component].type
        assert isinstance(component_type, Numeric)
        assert (component_type.precision, component_type.scale) == (10, 6)

    # league_season settings are a non-null JSON object with a Python-side default.
    season_settings = LeagueSeason.__table__.c.metadata
    assert isinstance(season_settings.type, JSON)
    assert season_settings.nullable is False
    assert season_settings.default is not None

    # Accounts carry a validated role and no owner link; owner associations live on user_league.
    app_user_role = AppUser.__table__.c.role
    assert isinstance(app_user_role.type, Text)
    assert app_user_role.nullable is False
    assert app_user_role.server_default is not None
    assert str(app_user_role.server_default.arg) == "member"
    invite_role = Invite.__table__.c.role
    assert isinstance(invite_role.type, Text)
    assert invite_role.nullable is False
    assert str(invite_role.server_default.arg) == "member"
    assert UserLeague.__table__.c.owner_id.nullable is True
    assert UserLeague.__table__.c.espn_s2_encrypted.nullable is True
    assert UserLeague.__table__.c.espn_swid_encrypted.nullable is True
