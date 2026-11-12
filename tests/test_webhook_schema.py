from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.webhook import RiskWebhookEventDto


def event_payload() -> dict:
    return {
        "event_id": "event-001",
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
                    "reason": "Transaction amount exceeds the configured USD threshold",
                    "transaction_id": "txn-001",
                    "risk_level": "high",
                    "rule_code": "HIGH_AMOUNT",
                }
            ],
        },
    }


def test_valid_event_serializes_with_nested_finding():
    event = RiskWebhookEventDto.model_validate(event_payload())

    data = event.model_dump(mode="json")

    assert data["type"] == "risk.detected"
    assert data["occurred_at"] == "2026-11-12T10:00:00Z"
    assert data["data"]["findings"] == [
        {
            "reason": "Transaction amount exceeds the configured USD threshold",
            "transaction_id": "txn-001",
            "risk_level": "high",
            "rule_code": "HIGH_AMOUNT",
        }
    ]


def test_event_id_must_be_non_empty():
    payload = event_payload()
    payload["event_id"] = ""

    with pytest.raises(ValidationError):
        RiskWebhookEventDto.model_validate(payload)


def test_findings_are_required():
    payload = event_payload()
    payload["data"]["findings"] = []

    with pytest.raises(ValidationError):
        RiskWebhookEventDto.model_validate(payload)


def test_naive_timestamp_is_rejected():
    payload = event_payload()
    payload["occurred_at"] = datetime(2026, 11, 12, 10, 0)

    with pytest.raises(ValidationError):
        RiskWebhookEventDto.model_validate(payload)


def test_summary_counts_must_match_findings():
    payload = event_payload()
    payload["data"]["summary"]["total_findings"] = 2

    with pytest.raises(ValidationError):
        RiskWebhookEventDto.model_validate(payload)


def test_unknown_fields_are_rejected():
    payload = event_payload()
    payload["data"]["transaction"] = {"amount": "25000.00"}

    with pytest.raises(ValidationError):
        RiskWebhookEventDto.model_validate(payload)
