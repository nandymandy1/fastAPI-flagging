from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_risk_analysis_service
from app.schemas import (
    AnalyzeTransactionsDto,
    RiskAnalysisResponseDto,
)
from app.services import RiskAnalysisService

router = APIRouter(prefix="/risk", tags=["Risk Monitor"])


@router.post("/analyze", response_model=RiskAnalysisResponseDto)
def analyze_transactions(
    payload: AnalyzeTransactionsDto,
    service: Annotated[RiskAnalysisService, Depends(get_risk_analysis_service)],
) -> RiskAnalysisResponseDto:
    return service.analyze(payload)
