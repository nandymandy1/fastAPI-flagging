import base64
import re
from datetime import UTC, datetime

from standardwebhooks.webhooks import Webhook

from app.schemas.webhook import RiskWebhookEventDto

WEBHOOK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def validate_webhook_secret(secret: str) -> None:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Webhook secret must not be blank")

    if not secret.startswith("whsec_"):
        raise ValueError("Webhook secret must use the whsec_ prefix")

    encoded_secret = secret.removeprefix("whsec_")

    if not encoded_secret:
        raise ValueError("Webhook secret must not be blank")

    try:
        decoded_secret = base64.b64decode(
            encoded_secret + "=" * (-len(encoded_secret) % 4), validate=True
        )

    except ValueError as exc:
        raise ValueError("Webhook secret must be valid Base64") from exc

    if not decoded_secret:
        raise ValueError("Webhook secret must not be blank")


def sign_webhook(
    event: RiskWebhookEventDto, secret: str, timestamp: datetime | None = None
) -> tuple[bytes, dict[str, str]]:
    """Serialize and sign a validated Standard Webhooks event."""
    if not WEBHOOK_ID_PATTERN.fullmatch(event.event_id):
        raise ValueError("Invalid webhook event ID")

    validate_webhook_secret(secret)

    attempt_timestamp = timestamp or datetime.now(UTC)

    if attempt_timestamp.tzinfo is None or attempt_timestamp.utcoffset() is None:
        raise ValueError("Webhook timestamp must be timezone-aware")

    attempt_timestamp = attempt_timestamp.astimezone(UTC).replace(microsecond=0)

    body_text = event.model_dump_json()
    signature = Webhook(secret).sign(event.event_id, attempt_timestamp, body_text)

    return body_text.encode(), {
        "webhook-id": event.event_id,
        "webhook-timestamp": str(int(attempt_timestamp.timestamp())),
        "webhook-signature": signature,
        "content-type": "application/json",
    }
