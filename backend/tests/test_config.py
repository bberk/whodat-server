import pytest

from app.api.main import create_app
from app.config import DEFAULT_SECRET_KEY, Settings, get_settings


def test_settings_have_dev_defaults() -> None:
    settings = Settings()
    assert settings.database_url
    assert settings.env
    assert settings.secret_key


def test_refresh_limits_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRESH_LEAGUE_INTERVAL_SECONDS", "12")
    monkeypatch.setenv("REFRESH_USER_LIMIT", "4")
    monkeypatch.setenv("REFRESH_USER_WINDOW_SECONDS", "120")
    monkeypatch.setenv("SEASON_REFRESH_LEAGUE_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("SEASON_REFRESH_USER_LIMIT", "25")
    monkeypatch.setenv("SEASON_REFRESH_USER_WINDOW_SECONDS", "600")

    settings = Settings(_env_file=None)

    assert settings.refresh_league_interval_seconds == 12
    assert settings.refresh_user_limit == 4
    assert settings.refresh_user_window_seconds == 120
    assert settings.season_refresh_league_interval_seconds == 0
    assert settings.season_refresh_user_limit == 25
    assert settings.season_refresh_user_window_seconds == 600


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_league_credentials_key_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEAGUE_CREDENTIALS_KEY", raising=False)
    assert Settings(_env_file=None).league_credentials_key is None


def test_league_credentials_key_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", "test-only-placeholder")
    assert Settings(_env_file=None).league_credentials_key == "test-only-placeholder"


def test_settings_do_not_expose_espn_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-AU-13: application settings have no environment ESPN credential path."""
    monkeypatch.setenv("ESPN_S2", "environment-s2-must-be-ignored")
    monkeypatch.setenv("ESPN_SWID", "environment-swid-must-be-ignored")

    settings = Settings(_env_file=None)

    assert "espn_s2" not in Settings.model_fields
    assert "espn_swid" not in Settings.model_fields
    assert "espn_s2" not in settings.model_dump()
    assert "espn_swid" not in settings.model_dump()


def test_create_app_refuses_insecure_default_secret_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env", ["local", "test"])
def test_create_app_allows_default_secret_in_local_and_test(
    monkeypatch: pytest.MonkeyPatch,
    env: str,
) -> None:
    monkeypatch.setenv("ENV", env)
    monkeypatch.setenv("SECRET_KEY", DEFAULT_SECRET_KEY)
    get_settings.cache_clear()
    try:
        assert create_app() is not None
    finally:
        get_settings.cache_clear()


def test_create_app_allows_production_with_a_custom_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a-long-production-only-secret")
    get_settings.cache_clear()
    try:
        assert create_app() is not None
    finally:
        get_settings.cache_clear()
