from app.config.config import Settings


def test_default_configuration():
    settings = Settings(_env_file=None)

    assert settings.api_prefix == "/api/v1"
    assert settings.app_env in {
        "development",
        "staging",
        "production",
    }


def test_default_bedrock_configuration(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_TIMEOUT_SECONDS", raising=False)
    settings = Settings(_env_file=None)

    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id is None
    assert settings.bedrock_timeout_seconds == 60
