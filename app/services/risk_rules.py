from collections import defaultdict
from app.schemas.transaction import TransactionDto
from app.schemas.risk import RiskFindingDto, RiskLevel, RiskRuleCode
from app.constants import (
    HIGH_AMOUNT_THRESHOLDS,
    TRANSACTION_WINDOW_DURATION,
    MAX_TRANSACTION_COUNT_IN_WINDOW,
)


def check_high_amount(transaction: TransactionDto) -> RiskFindingDto | None:
    threshold = HIGH_AMOUNT_THRESHOLDS.get(transaction.currency)

    if threshold is None or transaction.amount <= threshold:
        return None

    return RiskFindingDto(
        risk_level=RiskLevel.HIGH,
        rule_code=RiskRuleCode.HIGH_AMOUNT,
        transaction_id=transaction.transaction_id,
        reason=(
            "Transaction amount exceeds the configured "
            f"{transaction.currency} threshold"
        ),
    )


def check_high_velocity(transactions: list[TransactionDto]) -> list[RiskFindingDto]:
    findings: list[RiskFindingDto] = []
    customer_transactions = defaultdict(list)

    for transaction in transactions:
        customer_transactions[transaction.customer_id].append(transaction)

    threshold = MAX_TRANSACTION_COUNT_IN_WINDOW
    window_duration = TRANSACTION_WINDOW_DURATION

    for customer_id, txn_list in customer_transactions.items():
        # Sort transactions by timestamp
        txn_list.sort(key=lambda txn: txn.timestamp)
        left = 0

        for right in range(len(txn_list)):
            current = txn_list[right]
            while current.timestamp - txn_list[left].timestamp > window_duration:
                left += 1

            window_count = right - left + 1

            if window_count >= threshold:
                findings.append(
                    RiskFindingDto(
                        risk_level=RiskLevel.HIGH,
                        rule_code=RiskRuleCode.HIGH_VELOCITY,
                        transaction_id=current.transaction_id,
                        reason=(
                            f"Customer {customer_id} performed "
                            f"{window_count} transactions "
                            "within 5 minutes"
                        ),
                    )
                )

    return findings
