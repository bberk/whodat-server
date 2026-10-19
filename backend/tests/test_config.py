import pytest

from app.config import Settings, get_settings


def test_settings_have_dev_defaults() -> None:
    settings = Settings()
    assert settings.database_url
    assert settings.env
    assert settings.secret_key


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_league_credentials_key_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEAGUE_CREDENTIALS_KEY", raising=False)
    assert Settings(_env_file=None).league_credentials_key is None


def test_league_credentials_key_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEAGUE_CREDENTIALS_KEY", "test-only-placeholder")
    assert Settings(_env_file=None).league_credentials_key == "test-only-placeholder"
