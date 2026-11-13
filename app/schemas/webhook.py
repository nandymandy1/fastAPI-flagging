from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .risk import AiObservationDto, RiskFindingDto, RiskSummaryDto


class RiskWebhookDataDto(BaseModel):
    summary: RiskSummaryDto
    findings: list[RiskFindingDto] = Field(default_factory=list)
    ai_observations: list[AiObservationDto] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_summary_counts(self) -> "RiskWebhookDataDto":
        if not self.findings and not self.ai_observations:
            raise ValueError("Webhook event requires a finding or AI observation")

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
