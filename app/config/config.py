from functools import lru_cache

import boto3
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    debug: bool = False
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    app_name: str = "Risk Monitor"
    aws_region: str = "us-east-1"
    bedrock_model_id: str | None = None
    bedrock_timeout_seconds: int = 60
    api_key: str | None = None
    api_key_secret_arn: str | None = None
    dynamodb_table_name: str | None = None
    webhook_enabled: bool = False
    webhook_url: str | None = None
    webhook_signing_secret: SecretStr | None = None
    webhook_signing_secret_arn: str | None = None

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    if settings.api_key_secret_arn:
        settings.api_key = _secret_value(settings.api_key_secret_arn)

    if settings.webhook_signing_secret_arn:
        settings.webhook_signing_secret = SecretStr(
            _secret_value(settings.webhook_signing_secret_arn)
        )

    return settings


def _secret_value(secret_arn: str) -> str:
    value = (
        boto3.client("secretsmanager")
        .get_secret_value(SecretId=secret_arn)
        .get("SecretString")
    )

    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("Runtime secret is unavailable")

    return value
