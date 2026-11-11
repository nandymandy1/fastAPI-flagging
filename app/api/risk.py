from fastapi import APIRouter
from app.schemas import (
    AnalyzeTransactionsDto,
    RiskAnalysisResponseDto,
)

from app.services import RiskAnalysisService

router = APIRouter(prefix="/risk", tags=["Risk Monitor"])


@router.post("/analyze", response_model=RiskAnalysisResponseDto)
def analyze_transactions(payload: AnalyzeTransactionsDto):
    service = RiskAnalysisService()
    return service.analyze(payload)
