from app.config.config import Settings


def test_default_configuration():
    settings = Settings(_env_file=None)

    assert settings.api_prefix == "/api/v1"
    assert settings.app_env in {
        "development",
        "staging",
        "production",
    }
