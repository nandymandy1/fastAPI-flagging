from app.services.risk_analysis import RiskAnalysisService


def get_risk_analysis_service() -> RiskAnalysisService:
    return RiskAnalysisService()
