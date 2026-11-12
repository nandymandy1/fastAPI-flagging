import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config.config import Settings, get_settings
from app.dependencies import (
    RiskAgentBuilder,
    get_risk_agent_builder,
    get_risk_analysis_service,
    require_api_key,
)
from app.schemas import (
    AnalyzeTransactionsDto,
    RiskAnalysisResponseDto,
)
from app.services import RiskAnalysisService

router = APIRouter(prefix="/risk", tags=["Risk Monitor"])


@router.post(
    "/analyze",
    response_model=RiskAnalysisResponseDto,
    response_model_exclude_none=True,
    dependencies=[Depends(require_api_key)],
)
async def analyze_transactions(
    payload: AnalyzeTransactionsDto,
    service: Annotated[RiskAnalysisService, Depends(get_risk_analysis_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    agent_builder: Annotated[RiskAgentBuilder | None, Depends(get_risk_agent_builder)],
    include_ai: bool = False,
) -> RiskAnalysisResponseDto:
    analysis = service.analyze(payload)
    if not include_ai:
        return analysis

    if agent_builder is None:
        analysis.ai_status = "unavailable"
        return analysis

    try:
        async with asyncio.timeout(settings.bedrock_timeout_seconds):
            result = await agent_builder(analysis).invoke_async(
                "Call get_verified_risk_findings before briefly explaining the "
                "verified risk findings."
            )
        tool_metrics = result.metrics.tool_metrics.get("get_verified_risk_findings")
        summary = str(result).strip()
        if (
            result.stop_reason == "end_turn"
            and tool_metrics
            and tool_metrics.success_count > 0
            and tool_metrics.error_count == 0
            and summary
        ):
            analysis.ai_summary = summary
            analysis.ai_status = "generated"
            return analysis
    except Exception:  # noqa: BLE001
        analysis.ai_status = "unavailable"
        return analysis

    analysis.ai_status = "unavailable"
    return analysis
