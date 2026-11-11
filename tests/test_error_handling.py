import json

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_risk_analysis_service
from app.errors import AppError
from app.main import app


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_validation_errors_use_the_standard_response_shape():
    client = TestClient(app)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"] == "Request validation failed"
    assert response.json()["error"]["details"] == [
        {
            "field": "transactions",
            "code": "TOO_SHORT",
            "message": "List should have at least 1 item after validation, not 0",
        }
    ]


def test_validation_errors_do_not_expose_transaction_payloads():
    client = TestClient(app)
    payload = {
        "transactions": [
            {
                "transaction_id": "sensitive-transaction-id",
                "customer_id": "sensitive-customer-id",
                "amount": "100.00",
                "currency": "USD",
                "merchant": "Sensitive Merchant",
                "timestamp": "2026-11-11T10:00:00Z",
            },
            {
                "transaction_id": "sensitive-transaction-id",
                "customer_id": "sensitive-customer-id",
                "amount": "200.00",
                "currency": "USD",
                "merchant": "Sensitive Merchant",
                "timestamp": "2026-11-11T10:01:00Z",
            },
        ]
    }

    response = client.post("/api/v1/risk/analyze", json=payload)
    response_body = json.dumps(response.json())

    assert response.status_code == 422
    assert set(response.json()["error"]["details"][0]) == {
        "field",
        "code",
        "message",
    }
    assert "sensitive-transaction-id" not in response_body
    assert "sensitive-customer-id" not in response_body
    assert "Sensitive Merchant" not in response_body


def test_app_errors_use_the_standard_response_shape():
    def raise_app_error():
        raise AppError("UPSTREAM_UNAVAILABLE", "Risk service is unavailable", 503)

    app.dependency_overrides[get_risk_analysis_service] = raise_app_error
    client = TestClient(app)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "UPSTREAM_UNAVAILABLE",
            "message": "Risk service is unavailable",
            "details": [],
        }
    }


def test_unexpected_errors_do_not_expose_internal_details():
    def raise_unexpected_error():
        raise RuntimeError("database password leaked")

    app.dependency_overrides[get_risk_analysis_service] = raise_unexpected_error
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Internal server error",
            "details": [],
        }
    }


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({}, "transactions", "MISSING"),
        (
            {"transactions": [{"amount": "not-a-number"}]},
            "transactions[0].amount",
            "DECIMAL_PARSING",
        ),
        (
            {"transactions": [{"amount": "-1", "currency": "JPY"}]},
            "transactions[0].amount",
            "GREATER_THAN",
        ),
        (
            {"transactions": [{"currency": "usd"}]},
            "transactions[0].currency",
            "STRING_PATTERN_MISMATCH",
        ),
        (
            {"transactions": [{"merchant": ""}]},
            "transactions[0].merchant",
            "STRING_TOO_SHORT",
        ),
        (
            {"transactions": [{"timestamp": "not-a-date"}]},
            "transactions[0].timestamp",
            "DATETIME_FROM_DATE_PARSING",
        ),
    ],
)
def test_validation_errors_have_readable_fields_and_codes(payload, field, code):
    client = TestClient(app)

    response = client.post("/api/v1/risk/analyze", json=payload)

    assert response.status_code == 422
    assert any(
        detail["field"] == field and detail["code"] == code
        for detail in response.json()["error"]["details"]
    )


def test_custom_and_model_validation_errors_are_serialized():
    client = TestClient(app)
    transaction = {
        "transaction_id": "duplicate",
        "customer_id": "cust_101",
        "amount": "100.00",
        "currency": "USD",
        "merchant": "Amazon",
        "timestamp": "2026-11-11T10:00:00Z",
    }
    payload = {"transactions": [transaction, transaction]}

    response = client.post("/api/v1/risk/analyze", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {
            "field": "request",
            "code": "VALUE_ERROR",
            "message": "Value error, All transaction IDs must be unique",
        }
    ]


def test_unsupported_currency_uses_its_custom_error_code():
    client = TestClient(app)

    response = client.post(
        "/api/v1/risk/analyze",
        json={"transactions": [{"currency": "JPY"}]},
    )

    assert response.status_code == 422
    assert {
        "field": "transactions[0].currency",
        "code": "UNSUPPORTED_CURRENCY",
        "message": "Currency is not supported",
    } in response.json()["error"]["details"]


def test_multiple_validation_errors_have_separate_indexed_details():
    client = TestClient(app)
    payload = {
        "transactions": [
            {
                "transaction_id": "txn_001",
                "customer_id": "cust_101",
                "amount": "-1.00",
                "currency": "JPY",
                "merchant": "Amazon",
                "timestamp": "2026-11-11T10:00:00Z",
            }
        ]
    }

    response = client.post("/api/v1/risk/analyze", json=payload)
    details = response.json()["error"]["details"]

    assert response.status_code == 422
    assert {(detail["field"], detail["code"]) for detail in details} == {
        ("transactions[0].amount", "GREATER_THAN"),
        ("transactions[0].currency", "UNSUPPORTED_CURRENCY"),
    }


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code"),
    [
        ("get", "/api/v1/missing", 404, "NOT_FOUND"),
        ("post", "/api/v1/health/", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_http_errors_use_the_standard_response_shape(method, path, status_code, code):
    client = TestClient(app)

    response = getattr(client, method)(path)

    assert response.status_code == status_code
    assert response.json() == {
        "error": {
            "code": code,
            "message": response.reason_phrase,
            "details": [],
        }
    }


def test_risk_service_can_be_overridden():
    class StubRiskAnalysisService:
        def analyze(self, payload):
            assert len(payload.transactions) == 1
            return {
                "status": "completed",
                "summary": {
                    "total_findings": 0,
                    "total_transactions": 1,
                    "flagged_transactions": 0,
                },
                "findings": [],
            }

    app.dependency_overrides[get_risk_analysis_service] = StubRiskAnalysisService
    client = TestClient(app)

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
