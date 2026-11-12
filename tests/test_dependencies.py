from unittest.mock import Mock

import pytest

from app.config.config import Settings
from app.dependencies import get_idempotency_store
from app.services.idempotency import IdempotencyStore


@pytest.mark.parametrize("table_name", [None, "   "])
def test_idempotency_store_is_disabled_without_a_table(monkeypatch, table_name):
    resource = Mock()
    monkeypatch.setattr("app.dependencies.boto3.resource", resource)

    store = get_idempotency_store(
        Settings(_env_file=None, dynamodb_table_name=table_name)
    )

    assert store is None
    resource.assert_not_called()


def test_idempotency_store_uses_configured_table(monkeypatch):
    table = Mock()
    resource = Mock()
    resource.return_value.Table.return_value = table
    monkeypatch.setattr("app.dependencies.boto3.resource", resource)

    store = get_idempotency_store(
        Settings(
            _env_file=None,
            aws_region="test-region",
            dynamodb_table_name="risk-monitor",
        )
    )

    assert isinstance(store, IdempotencyStore)
    assert store.table is table
    resource.assert_called_once_with("dynamodb", region_name="test-region")
    resource.return_value.Table.assert_called_once_with("risk-monitor")
