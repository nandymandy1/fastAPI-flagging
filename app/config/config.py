from functools import lru_cache

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
    dynamodb_table_name: str | None = None

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
