from collections.abc import Callable
from secrets import compare_digest
from typing import Annotated

import boto3
from fastapi import Depends, Header, HTTPException, status
from strands import Agent

from .config.config import Settings, get_settings
from .schemas.risk import RiskAnalysisResponseDto
from .schemas.transaction import AnalyzeTransactionsDto
from .services import (
    IdempotencyStore,
    RiskAnalysisService,
    WebhookService,
    create_risk_agent,
)

RiskAgentBuilder = Callable[[AnalyzeTransactionsDto, RiskAnalysisResponseDto], Agent]


def get_risk_analysis_service() -> RiskAnalysisService:
    return RiskAnalysisService()


def get_idempotency_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IdempotencyStore | None:
    if not settings.dynamodb_table_name or not settings.dynamodb_table_name.strip():
        return None
    table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(
        settings.dynamodb_table_name
    )
    return IdempotencyStore(table)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.api_key or not settings.api_key.strip():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if not x_api_key or not compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


def get_risk_agent_builder(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RiskAgentBuilder | None:
    if not settings.bedrock_model_id or not settings.bedrock_model_id.strip():
        return None

    def build(
        payload: AnalyzeTransactionsDto,
        analysis: RiskAnalysisResponseDto,
    ) -> Agent:
        return create_risk_agent(
            payload,
            analysis,
            settings.aws_region,
            settings.bedrock_model_id,
        )

    return build


def get_webhook_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> WebhookService | None:
    if not settings.webhook_enabled:
        return None

    secret = settings.webhook_signing_secret
    if (
        not settings.webhook_url
        or not settings.webhook_url.strip()
        or secret is None
        or not secret.get_secret_value().strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook service unavailable",
        )

    try:
        return WebhookService(settings.webhook_url, secret.get_secret_value())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook service unavailable",
        ) from exc
