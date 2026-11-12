from app.schemas.risk import (
    RiskAnalysisResponseDto,
    RiskFindingDto,
    RiskSummaryDto,
)
from app.schemas.transaction import AnalyzeTransactionsDto
from app.services.risk_rules import check_high_amount, check_high_velocity


class RiskAnalysisService:
    def analyze(self, payload: AnalyzeTransactionsDto) -> RiskAnalysisResponseDto:
        findings: list[RiskFindingDto] = []

        # 1. Transaction-level risk detection
        for transaction in payload.transactions:
            finding = check_high_amount(transaction)

            if finding is not None:
                findings.append(finding)

        # 2. Batch-level velocity detection
        velocity_findings = check_high_velocity(payload.transactions)
        findings.extend(velocity_findings)

        # 3. Count unique flagged transactions
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
