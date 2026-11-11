from app.schemas.transaction import AnalyzeTransactionsDto
from app.schemas.risk import (
    RiskAnalysisResponseDto,
    RiskSummaryDto,
    RiskFindingDto,
)

from app.services.risk_rules import check_high_amount


class RiskAnalysisService:
    def analyze(self, payload: AnalyzeTransactionsDto) -> RiskAnalysisResponseDto:

        findings: list[RiskFindingDto] = []

        for transaction in payload.transactions:
            finding = check_high_amount(transaction)

            if finding is not None:
                findings.append(finding)

        flagged_ids = {finding.transaction_id for finding in findings}

        return RiskAnalysisResponseDto(
            findings=findings,
            status="completed",
            summary=RiskSummaryDto(
                flagged_transactions=len(flagged_ids),
                total_findings=len(findings),
                total_transactions=len(payload.transactions),
            ),
        )
