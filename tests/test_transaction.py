from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_idempotency_store, require_api_key
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_authentication():
    store = Mock()
    store.get.return_value = None
    store.reserve.return_value = {"reservation_id": "test-reservation"}
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_idempotency_store] = lambda: store
    client.headers["Idempotency-Key"] = "test-key"
    yield
    app.dependency_overrides.pop(require_api_key, None)
    app.dependency_overrides.pop(get_idempotency_store, None)
    client.headers.pop("Idempotency-Key", None)


def test_valid_transaction_batch():
    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "150.00",
                    "currency": "USD",
                    "merchant": "Amazon",
                    "timestamp": "2026-11-11T10:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["total_transactions"] == 1


def test_negative_amount():
    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "-150.00",
                    "currency": "USD",
                    "merchant": "Amazon",
                    "timestamp": "2026-11-11T10:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 422


def test_empty_batch():
    response = client.post(
        "/api/v1/risk/analyze",
        json={"transactions": []},
    )

    assert response.status_code == 422


def test_risk_analysis():
    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "25000.00",
                    "currency": "USD",
                    "merchant": "Merchant ABC",
                    "timestamp": "2026-11-11T10:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["summary"]["total_findings"] == 1
    assert data["summary"]["total_transactions"] == 1
    assert data["summary"]["flagged_transactions"] == 1
    assert data["findings"][0]["rule_code"] == "HIGH_AMOUNT"


def test_no_risk_findings():
    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_002",
                    "customer_id": "cust_101",
                    "amount": "100.00",
                    "currency": "USD",
                    "merchant": "Amazon",
                    "timestamp": "2026-11-11T10:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["summary"]["flagged_transactions"] == 0
    assert data["findings"] == []


def test_duplicate_transaction_ids():
    # Send two otherwise valid transactions with the same ID
    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "100.00",
                    "currency": "USD",
                    "merchant": "Amazon",
                    "timestamp": "2026-11-11T10:00:00Z",
                },
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "200.00",
                    "currency": "USD",
                    "merchant": "Walmart",
                    "timestamp": "2026-11-11T10:01:00Z",
                },
            ]
        },
    )

    assert response.status_code == 422
