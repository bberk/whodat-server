from app.config import Settings, get_settings


def test_settings_have_dev_defaults() -> None:
    settings = Settings()
    assert settings.database_url
    assert settings.env
    assert settings.secret_key


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
