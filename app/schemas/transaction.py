from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.constants.rule_constants import HIGH_AMOUNT_THRESHOLDS

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)
]


class TransactionDto(BaseModel):
    currency: Currency
    timestamp: datetime
    customer_id: Identifier
    transaction_id: Identifier
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    merchant: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include timezone information")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in HIGH_AMOUNT_THRESHOLDS:
            raise PydanticCustomError(
                "UNSUPPORTED_CURRENCY",
                "Currency is not supported",
            )

        return value


class AnalyzeTransactionsDto(BaseModel):
    transactions: list[TransactionDto] = Field(min_length=1, max_length=100)

    @field_validator("transactions")
    @classmethod
    def validate_unique_transactions(
        cls, transactions: list[TransactionDto]
    ) -> list[TransactionDto]:
        ids = [txn.transaction_id for txn in transactions]
        if len(ids) != len(set(ids)):
            raise PydanticCustomError(
                "DUPLICATE_TRANSACTION_ID",
                "Transaction IDs must be unique",
            )
        return transactions
