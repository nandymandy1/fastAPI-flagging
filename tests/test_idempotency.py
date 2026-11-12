from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.services.idempotency import (
    MAX_WEBHOOK_ATTEMPTS,
    IdempotencyStore,
    IdempotencyStoreError,
)


def conditional_failure():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
    )


@pytest.fixture
def table():
    return Mock()


def test_reserve_creates_a_processing_record_with_conditional_insert(table):
    reservation = IdempotencyStore(table).reserve("key", "hash")

    assert reservation["status"] == "PROCESSING"
    assert reservation["event_id"]
    assert "ConditionExpression" in table.put_item.call_args.kwargs


def test_reserve_keeps_an_active_reservation(table):
    table.put_item.side_effect = conditional_failure()
    table.get_item.return_value = {"Item": {"expires_at": 9_999_999_999}}

    assert IdempotencyStore(table).reserve("key", "hash") is None


def test_reserve_allows_reclaim_at_expiry_boundary(table, monkeypatch):
    monkeypatch.setattr("app.services.idempotency.time", lambda: 100)

    IdempotencyStore(table).reserve("key", "hash")

    condition = table.put_item.call_args.kwargs["ConditionExpression"]
    assert condition.get_expression()["values"][1].get_expression()["operator"] == "<="


def test_get_is_strongly_consistent_and_ignores_expired_records(table):
    table.get_item.return_value = {"Item": {"expires_at": 0}}

    assert IdempotencyStore(table).get("key") is None
    table.get_item.assert_called_once_with(Key={"pk": "key"}, ConsistentRead=True)


def test_complete_preserves_three_argument_behavior(table):
    IdempotencyStore(table).complete("key", "reservation", {"status": "completed"})

    kwargs = table.update_item.call_args.kwargs
    assert kwargs["ExpressionAttributeValues"][":response"] == {"status": "completed"}
    assert "webhook" not in kwargs["UpdateExpression"]


def test_complete_atomically_persists_pending_webhook_intent(table):
    event = {"event_id": "event-1", "type": "risk.detected"}
    response = {"status": "completed"}

    IdempotencyStore(table).complete("key", "reservation", response, event)

    kwargs = table.update_item.call_args.kwargs
    assert table.update_item.call_count == 1
    assert kwargs["ExpressionAttributeValues"][":response"] == response
    assert kwargs["ExpressionAttributeValues"][":webhook"] == {
        "status": "PENDING",
        "event": event,
        "attempts": 0,
    }
    assert "webhook" in kwargs["UpdateExpression"]
    assert "event-1" in _condition_values(kwargs["ConditionExpression"])


def test_completion_failure_is_sanitized(table):
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "UpdateItem"
    )

    with pytest.raises(IdempotencyStoreError, match="Idempotency completion failed"):
        IdempotencyStore(table).complete("key", "reservation", {})


def test_claim_uses_single_conditional_update_with_recovery_conditions(
    table, monkeypatch
):
    monkeypatch.setattr("app.services.idempotency.time", lambda: 100)
    table.update_item.return_value = {
        "Attributes": {
            "webhook": {
                "status": "DELIVERING",
                "event": {"event_id": "event-1"},
                "attempts": 1,
                "claim_id": "claim-1",
            }
        }
    }

    webhook = IdempotencyStore(table).claim_webhook("key")
    kwargs = table.update_item.call_args.kwargs
    values = _condition_values(kwargs["ConditionExpression"])

    assert table.update_item.call_count == 1
    assert webhook["event"]["event_id"] == "event-1"
    assert kwargs["ReturnValues"] == "ALL_NEW"
    assert {"PENDING", "FAILED", "DELIVERING"} <= {
        value for value in values if isinstance(value, str)
    }
    assert MAX_WEBHOOK_ATTEMPTS in values
    assert 100 in values


def test_conditional_claim_conflict_returns_none(table):
    table.update_item.side_effect = conditional_failure()

    assert IdempotencyStore(table).claim_webhook("key") is None


def test_unexpected_claim_error_is_sanitized(table):
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "UpdateItem"
    )

    with pytest.raises(IdempotencyStoreError, match="Webhook claim failed"):
        IdempotencyStore(table).claim_webhook("key")


@pytest.mark.parametrize(
    ("method", "expected_status"),
    [("mark_webhook_delivered", "DELIVERED"), ("mark_webhook_failed", "FAILED")],
)
def test_terminal_webhook_transitions_require_claim_ownership(
    table, method, expected_status
):
    getattr(IdempotencyStore(table), method)("key", "claim-1")

    kwargs = table.update_item.call_args.kwargs
    assert kwargs["ExpressionAttributeValues"][":webhook_status"] == expected_status
    assert "claim-1" in _condition_values(kwargs["ConditionExpression"])
    assert (
        "REMOVE webhook.claim_id, webhook.claim_expires_at"
        in kwargs["UpdateExpression"]
    )
    assert "response" not in kwargs["UpdateExpression"]


def test_release_requires_processing_reservation_ownership(table):
    IdempotencyStore(table).release("key", "reservation")

    assert "ConditionExpression" in table.delete_item.call_args.kwargs


def _condition_values(condition):
    values = []
    for value in condition.get_expression()["values"]:
        if hasattr(value, "get_expression"):
            values.extend(_condition_values(value))
        elif isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)
    return values
