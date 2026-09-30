from app.core.config import Settings


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Nexus AI Workspace API")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")

    test_settings = Settings(_env_file=None)

    assert test_settings.app_name == "Nexus AI Workspace API"
    assert test_settings.environment == "test"
    assert test_settings.debug is True
