from collections.abc import Callable
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from strands import Agent

from app.config.config import Settings, get_settings
from app.schemas.risk import RiskAnalysisResponseDto
from app.services.risk_agent import create_risk_agent
from app.services.risk_analysis import RiskAnalysisService

RiskAgentBuilder = Callable[[RiskAnalysisResponseDto], Agent]


def get_risk_analysis_service() -> RiskAnalysisService:
    return RiskAnalysisService()


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

    def build(analysis: RiskAnalysisResponseDto) -> Agent:
        return create_risk_agent(
            analysis,
            settings.aws_region,
            settings.bedrock_model_id,
        )

    return build
