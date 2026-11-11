from decimal import Decimal
from datetime import datetime, timezone
from app.schemas import TransactionDto
from app.services import check_high_amount


def make_transaction(amount: str):
    return TransactionDto(
        transaction_id="txn_001",
        customer_id="cust_101",
        amount=Decimal(amount),
        currency="USD",
        merchant="Example Merchant",
        timestamp=datetime.now(timezone.utc),
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
