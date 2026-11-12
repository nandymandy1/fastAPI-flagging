from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


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


AiTransactionId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class AiObservationPattern(str, Enum):
    POSSIBLE_SPLIT_PAYMENTS = "possible_split_payments"
    REPEATED_BATCH_PATTERN = "repeated_batch_pattern"
    TRANSACTION_RELATIONSHIP = "transaction_relationship"


class AiObservationDto(BaseModel):
    pattern: AiObservationPattern
    transaction_ids: list[AiTransactionId] = Field(min_length=1, max_length=10)
    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    status: Literal["advisory", "review"]

    model_config = ConfigDict(extra="forbid")

    @field_validator("transaction_ids")
    @classmethod
    def validate_unique_transaction_ids(cls, transaction_ids: list[str]) -> list[str]:
        if len(transaction_ids) != len(set(transaction_ids)):
            raise ValueError("Observation transaction IDs must be unique")
        return transaction_ids


class AiAssessmentDto(BaseModel):
    ai_summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    ai_observations: list[AiObservationDto] = Field(max_length=5)

    model_config = ConfigDict(extra="forbid")


class RiskAnalysisResponseDto(BaseModel):
    status: str
    summary: RiskSummaryDto
    findings: list[RiskFindingDto]
    ai_summary: str | None = None
    ai_status: Literal["generated", "unavailable"] | None = None
    ai_observations: list[AiObservationDto] | None = None
