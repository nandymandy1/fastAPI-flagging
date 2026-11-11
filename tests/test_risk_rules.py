from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.schemas import TransactionDto
from app.services import check_high_amount
from app.services.risk_rules import HIGH_AMOUNT_THRESHOLDS, check_high_velocity


def make_transaction(
    amount: str,
    currency: str = "USD",
    *,
    customer_id: str = "cust_101",
    transaction_id: str = "txn_001",
    timestamp: datetime | None = None,
):
    return TransactionDto(
        transaction_id=transaction_id,
        customer_id=customer_id,
        amount=Decimal(amount),
        currency=currency,
        merchant="Example Merchant",
        timestamp=timestamp or datetime.now(UTC),
    )


def test_high_amount_detected():
    transaction = make_transaction("25000")
    result = check_high_amount(transaction)
    assert result is not None
    assert result.rule_code == "HIGH_AMOUNT"
    assert result.risk_level == "high"


def test_normal_amount():
    transaction = make_transaction("500")
    result = check_high_amount(transaction)
    assert result is None


def test_exact_threshold():
    transaction = make_transaction("10000")
    result = check_high_amount(transaction)
    assert result is None


@pytest.mark.parametrize(
    "currency", [currency for currency in HIGH_AMOUNT_THRESHOLDS if currency != "USD"]
)
def test_high_amount_is_detected_for_each_supported_currency(currency: str):
    threshold = HIGH_AMOUNT_THRESHOLDS[currency]

    result = check_high_amount(
        make_transaction(str(threshold + Decimal("0.01")), currency)
    )

    assert result is not None
    assert result.rule_code == "HIGH_AMOUNT"


@pytest.mark.parametrize("currency", ["JPY", "XYZ"])
def test_high_amount_ignores_unsupported_currencies(currency: str):
    result = check_high_amount(make_transaction("99999999.99", currency))

    assert result is None


@pytest.mark.parametrize("currency", HIGH_AMOUNT_THRESHOLDS)
def test_exact_currency_threshold_is_not_high_risk(currency: str):
    result = check_high_amount(
        make_transaction(str(HIGH_AMOUNT_THRESHOLDS[currency]), currency)
    )

    assert result is None


BASE_TIME = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


def velocity_transaction(
    transaction_id: str, customer_id: str, minute: int
) -> TransactionDto:
    return make_transaction(
        "100.00",
        transaction_id=transaction_id,
        customer_id=customer_id,
        timestamp=BASE_TIME.replace(minute=minute),
    )


def test_high_velocity_detects_three_transactions_within_five_minutes():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 2),
            velocity_transaction("txn_003", "cust_101", 4),
        ]
    )

    assert [finding.transaction_id for finding in findings] == ["txn_003"]


def test_high_velocity_ignores_transactions_outside_the_window():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 3),
            velocity_transaction("txn_003", "cust_101", 6),
        ]
    )

    assert findings == []


def test_high_velocity_includes_the_exact_five_minute_boundary():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 2),
            velocity_transaction("txn_003", "cust_101", 5),
        ]
    )

    assert [finding.transaction_id for finding in findings] == ["txn_003"]


def test_high_velocity_sorts_unsorted_timestamps():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_003", "cust_101", 5),
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 2),
        ]
    )

    assert [finding.transaction_id for finding in findings] == ["txn_003"]


def test_high_velocity_keeps_customers_separate():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 1),
            velocity_transaction("txn_003", "cust_101", 2),
            velocity_transaction("txn_004", "cust_202", 0),
            velocity_transaction("txn_005", "cust_202", 1),
        ]
    )

    assert [finding.transaction_id for finding in findings] == ["txn_003"]


def test_high_velocity_returns_two_findings_for_four_transactions():
    findings = check_high_velocity(
        [
            velocity_transaction("txn_001", "cust_101", 0),
            velocity_transaction("txn_002", "cust_101", 1),
            velocity_transaction("txn_003", "cust_101", 2),
            velocity_transaction("txn_004", "cust_101", 3),
        ]
    )

    assert [finding.transaction_id for finding in findings] == ["txn_003", "txn_004"]
