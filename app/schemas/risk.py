from enum import Enum
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"
    MEDIUM = "medium"


class RiskRuleCode(str, Enum):
    HIGH_AMOUNT = "HIGH_AMOUNT"
    HIGH_VELOCITY = "HIGH_VELOCITY"


class RiskFindingDto(BaseModel):
    reason: str
    transaction_id: str
    risk_level: RiskLevel
    rule_code: RiskRuleCode


class RiskSummaryDto(BaseModel):
    total_findings: int = Field(ge=0)
    total_transactions: int = Field(ge=0)
    flagged_transactions: int = Field(ge=0)


class RiskAnalysisResponseDto(BaseModel):
    status: str
    summary: RiskSummaryDto
    findings: list[RiskFindingDto]
