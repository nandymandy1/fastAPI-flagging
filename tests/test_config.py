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


def test_default_api_and_dynamodb_configuration(monkeypatch):
    for name in (
        "API_KEY",
        "DYNAMODB_TABLE_NAME",
        "API_PREFIX",
        "APP_ENV",
        "APP_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)

    assert settings.api_key is None
    assert settings.dynamodb_table_name is None
    assert settings.api_prefix == "/api/v1"
    assert settings.app_env == "development"
    assert settings.app_name == "Risk Monitor"


def test_api_and_dynamodb_environment_overrides(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "test-risk-monitor")

    settings = Settings(_env_file=None)

    assert settings.api_key == "test-api-key"
    assert settings.dynamodb_table_name == "test-risk-monitor"
