from decimal import Decimal

from app.schemas.transaction import TransactionDto
from app.schemas.risk import RiskFindingDto, RiskLevel


HIGH_AMOUNT_THRESHOLD_USD = Decimal("10000.00")


def check_high_amount(transaction: TransactionDto) -> RiskFindingDto | None:
    if transaction.currency != "USD":
        return None

    if transaction.amount <= HIGH_AMOUNT_THRESHOLD_USD:
        return None

    return RiskFindingDto(
        transaction_id=transaction.transaction_id,
        rule_code="HIGH_AMOUNT",
        risk_level=RiskLevel.HIGH,
        reason=("Transaction amount exceeds the configured USD threshold"),
    )
