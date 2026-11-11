from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


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
