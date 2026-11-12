import base64
from datetime import UTC, datetime, timedelta, timezone

import pytest
from standardwebhooks.webhooks import Webhook, WebhookVerificationError

from app.schemas.webhook import RiskWebhookEventDto
from app.utils import sign_webhook

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()


@pytest.fixture
def event() -> RiskWebhookEventDto:
    return RiskWebhookEventDto.model_validate(
        {
            "event_id": "event_001",
            "type": "risk.detected",
            "schema_version": "1.0",
            "occurred_at": datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
            "data": {
                "summary": {
                    "total_findings": 1,
                    "total_transactions": 1,
                    "flagged_transactions": 1,
                },
                "findings": [
                    {
                        "reason": "Synthetic high amount finding",
                        "transaction_id": "txn-001",
                        "risk_level": "high",
                        "rule_code": "HIGH_AMOUNT",
                    }
                ],
            },
        }
    )


def current_time() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def test_valid_signature_verifies_exact_event_body(event):
    body, headers = sign_webhook(event, SECRET, current_time())

    verified = Webhook(SECRET).verify(body, headers)

    assert body == event.model_dump_json().encode()
    assert verified == event.model_dump(mode="json")


def test_tampered_body_is_rejected(event):
    body, headers = sign_webhook(event, SECRET, current_time())

    with pytest.raises(WebhookVerificationError):
        Webhook(SECRET).verify(body.replace(b"HIGH_AMOUNT", b"HIGH_VELOCITY"), headers)


@pytest.mark.parametrize("offset", [timedelta(minutes=-6), timedelta(minutes=6)])
def test_expired_or_future_timestamps_are_rejected(event, offset):
    body, headers = sign_webhook(event, SECRET, current_time() + offset)

    with pytest.raises(WebhookVerificationError):
        Webhook(SECRET).verify(body, headers)


def test_retries_preserve_event_identity_and_sign_each_attempt(event):
    first_time = current_time() - timedelta(minutes=2)
    second_time = first_time + timedelta(seconds=1)
    first_body, first_headers = sign_webhook(event, SECRET, first_time)
    second_body, second_headers = sign_webhook(event, SECRET, second_time)

    assert first_headers["webhook-id"] == second_headers["webhook-id"] == event.event_id
    assert first_body == second_body
    assert first_headers["webhook-timestamp"] != second_headers["webhook-timestamp"]
    assert first_headers["webhook-signature"] != second_headers["webhook-signature"]
    Webhook(SECRET).verify(first_body, first_headers)
    Webhook(SECRET).verify(second_body, second_headers)


def test_utc_normalization_produces_matching_headers_and_signatures(event):
    utc_timestamp = current_time()
    offset_timestamp = utc_timestamp.astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )

    _, utc_headers = sign_webhook(event, SECRET, utc_timestamp)
    _, offset_headers = sign_webhook(event, SECRET, offset_timestamp)

    assert utc_headers["webhook-timestamp"] == offset_headers["webhook-timestamp"]
    assert utc_headers["webhook-signature"] == offset_headers["webhook-signature"]


def test_unsafe_event_ids_are_rejected(event):
    unsafe_event = event.model_copy(update={"event_id": "event.001"})

    with pytest.raises(ValueError, match="Invalid webhook event ID"):
        sign_webhook(unsafe_event, SECRET, current_time())


def test_invalid_signing_secrets_are_rejected(event):
    with pytest.raises(ValueError):
        sign_webhook(event, "whsec_not base64!", current_time())
