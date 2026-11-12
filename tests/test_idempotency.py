from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.services.idempotency import IdempotencyStore, IdempotencyStoreError


def conditional_failure():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem"
    )


@pytest.fixture
def table():
    return Mock()


def test_first_reservation_succeeds(table):
    store = IdempotencyStore(table)

    reservation = store.reserve("key", "hash")

    assert reservation["status"] == "PROCESSING"
    assert reservation["pk"] == "key"
    assert reservation["request_hash"] == "hash"
    assert reservation["reservation_id"]
    assert reservation["event_id"]
    assert "ConditionExpression" in table.put_item.call_args.kwargs


def test_active_reservation_is_not_overwritten(table):
    table.put_item.side_effect = conditional_failure()
    table.get_item.return_value = {"Item": {"expires_at": 9999999999}}

    assert IdempotencyStore(table).reserve("key", "hash") is None


def test_expired_reservation_can_be_reclaimed(table):
    assert IdempotencyStore(table).reserve("key", "hash") is not None
    assert table.put_item.call_count == 1


def test_reservation_can_be_reclaimed_at_expiry_boundary(table, monkeypatch):
    monkeypatch.setattr("app.services.idempotency.time", lambda: 100)

    assert IdempotencyStore(table).reserve("key", "hash") is not None

    condition = table.put_item.call_args.kwargs["ConditionExpression"]
    assert condition.get_expression()["values"][1].get_expression()["operator"] == "<="


def test_get_uses_consistent_read_and_ignores_expired_items(table):
    table.get_item.return_value = {"Item": {"pk": "key", "expires_at": 0}}

    assert IdempotencyStore(table).get("key") is None
    table.get_item.assert_called_once_with(Key={"pk": "key"}, ConsistentRead=True)


def test_complete_stores_response_and_extends_expiry(table):
    store = IdempotencyStore(table)

    store.complete("key", "reservation", {"status": "completed"})

    values = table.update_item.call_args.kwargs["ExpressionAttributeValues"]
    assert values[":completed"] == "COMPLETED"
    assert values[":response"] == {"status": "completed"}
    assert values[":expires"] > 0
    assert "ConditionExpression" in table.update_item.call_args.kwargs


@pytest.mark.parametrize(
    "method, args", [("complete", ("key", "wrong", {})), ("release", ("key", "wrong"))]
)
def test_incorrect_reservation_cannot_change_another_request(table, method, args):
    table.update_item.side_effect = conditional_failure()
    table.delete_item.side_effect = conditional_failure()

    with pytest.raises(IdempotencyStoreError):
        getattr(IdempotencyStore(table), method)(*args)


def test_expired_reservation_cannot_complete(table):
    table.update_item.side_effect = conditional_failure()

    with pytest.raises(IdempotencyStoreError):
        IdempotencyStore(table).complete("key", "reservation", {})


def test_owned_processing_reservation_can_be_released(table):
    IdempotencyStore(table).release("key", "reservation")

    assert "ConditionExpression" in table.delete_item.call_args.kwargs


def test_unexpected_dynamodb_error_is_sanitized(table):
    table.get_item.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "GetItem"
    )

    with pytest.raises(
        IdempotencyStoreError, match="Idempotency storage request failed"
    ):
        IdempotencyStore(table).get("key")
