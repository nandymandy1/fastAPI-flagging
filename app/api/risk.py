from typing import Annotated

from fastapi import APIRouter, Depends

from app.config.config import Settings, get_settings
from app.dependencies import get_risk_analysis_service
from app.schemas import (
    AnalyzeTransactionsDto,
    RiskAnalysisResponseDto,
)
from app.services import RiskAnalysisService
from app.services.risk_agent import create_risk_agent

router = APIRouter(prefix="/risk", tags=["Risk Monitor"])


@router.post(
    "/analyze",
    response_model=RiskAnalysisResponseDto,
    response_model_exclude_none=True,
)
def analyze_transactions(
    payload: AnalyzeTransactionsDto,
    service: Annotated[RiskAnalysisService, Depends(get_risk_analysis_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    include_ai: bool = False,
) -> RiskAnalysisResponseDto:
    analysis = service.analyze(payload)
    if not include_ai:
        return analysis

    if not settings.bedrock_model_id or not settings.bedrock_model_id.strip():
        analysis.ai_status = "unavailable"
        return analysis

    try:
        result = create_risk_agent(
            analysis=analysis,
            region_name=settings.aws_region,
            model_id=settings.bedrock_model_id,
        )(
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
