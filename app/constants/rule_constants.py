from datetime import timedelta
from decimal import Decimal


HIGH_AMOUNT_THRESHOLDS = {
    "USD": Decimal("10000.00"),
    "INR": Decimal("1000000.00"),
    "SGD": Decimal("13000.00"),
    "AUD": Decimal("15000.00"),
    "GBP": Decimal("8000.00"),
    "EUR": Decimal("9000.00"),
    "CAD": Decimal("15000.00"),
}

MAX_TRANSACTION_COUNT_IN_WINDOW = 3
TRANSACTION_WINDOW_DURATION = timedelta(minutes=5)
HIGH_AMOUNT_THRESHOLD_USD = HIGH_AMOUNT_THRESHOLDS["USD"]
