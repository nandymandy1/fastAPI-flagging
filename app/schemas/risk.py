from enum import Enum
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskFindingDto(BaseModel):
    transaction_id: str
    rule_code: str
    risk_level: RiskLevel
    reason: str


class RiskSummaryDto(BaseModel):
    total_transactions: int = Field(ge=0)
    flagged_transactions: int = Field(ge=0)
    total_findings: int = Field(ge=0)


class RiskAnalysisResponseDto(BaseModel):
    status: str
    summary: RiskSummaryDto
    findings: list[RiskFindingDto]
