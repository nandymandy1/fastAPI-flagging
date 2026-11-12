from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.risk import RiskFindingDto, RiskSummaryDto


class RiskWebhookDataDto(BaseModel):
    summary: RiskSummaryDto
    findings: list[RiskFindingDto] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_summary_counts(self) -> "RiskWebhookDataDto":
        if self.summary.total_findings != len(self.findings):
            raise ValueError("Summary finding count does not match findings")
        if self.summary.flagged_transactions != len(
            {finding.transaction_id for finding in self.findings}
        ):
            raise ValueError(
                "Summary flagged transaction count does not match findings"
            )
        return self


class RiskWebhookEventDto(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    type: Literal["risk.detected"]
    schema_version: Literal["1.0"]
    occurred_at: AwareDatetime
    data: RiskWebhookDataDto

    model_config = ConfigDict(extra="forbid")
