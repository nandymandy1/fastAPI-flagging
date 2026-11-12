from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.config.config import Settings, get_settings
from app.dependencies import (
    get_idempotency_store,
    get_risk_agent_builder,
    require_api_key,
)
from app.main import app
from app.schemas.risk import AiAssessmentDto

PAYLOAD = {
    "transactions": [
        {
            "transaction_id": "txn_ai_001",
            "customer_id": "cust_ai_001",
            "amount": "25000.00",
            "currency": "USD",
            "merchant": "Test Merchant",
            "timestamp": "2026-11-11T10:00:00Z",
        }
    ]
}
CONTEXT_PAYLOAD = {
    "transactions": [
        {
            **PAYLOAD["transactions"][0],
            "transaction_id": "txn_context_001",
            "amount": "4900.00",
        },
        {
            **PAYLOAD["transactions"][0],
            "transaction_id": "txn_context_002",
            "amount": "4900.00",
        },
    ]
}


@pytest.fixture(autouse=True)
def overrides():
    store = Mock()
    store.get.return_value = None
    store.reserve.return_value = {"reservation_id": "test-reservation"}
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_idempotency_store] = lambda: store
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


@pytest.fixture
def client():
    with TestClient(app, headers={"Idempotency-Key": "test-key"}) as test_client:
        yield test_client


def set_settings(model_id: str | None) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, aws_region="test-region", bedrock_model_id=model_id
    )


def assessment(transaction_ids: list[str]) -> AiAssessmentDto:
    return AiAssessmentDto.model_validate(
        {
            "ai_summary": "Two related transactions merit review.",
            "ai_observations": [
                {
                    "pattern": "possible_split_payments",
                    "transaction_ids": transaction_ids,
                    "explanation": "The transactions form a closely related batch pattern.",
                    "status": "review",
                }
            ],
        }
    )


def agent_builder(
    output: AiAssessmentDto, stop_reason: str = "end_turn"
) -> tuple[Mock, Mock]:
    result = MagicMock()
    result.stop_reason = stop_reason
    result.structured_output = output
    result.metrics.tool_metrics = {
        name: SimpleNamespace(success_count=1, error_count=0)
        for name in ("get_verified_risk_findings", "get_validated_transactions")
    }
    agent = Mock(invoke_async=AsyncMock(return_value=result))
    return Mock(return_value=agent), agent


def test_explicitly_disabled_ai_preserves_deterministic_response(client):
    builder, _ = agent_builder(assessment(["txn_ai_001"]))
    app.dependency_overrides[get_risk_agent_builder] = lambda: builder

    response = client.post("/api/v1/risk/analyze?include_ai=false", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["findings"][0]["rule_code"] == "HIGH_AMOUNT"
    assert "ai_summary" not in response.json()


def test_configured_agent_adds_valid_contextual_observation_by_default(client):
    set_settings("configured-model")
    builder, agent = agent_builder(
        assessment(["txn_context_001", "txn_context_002"]), "tool_use"
    )
    app.dependency_overrides[get_risk_agent_builder] = lambda: builder

    response = client.post("/api/v1/risk/analyze", json=CONTEXT_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["findings"] == []
    assert response.json()["ai_status"] == "generated"
    assert response.json()["ai_observations"][0]["transaction_ids"] == [
        "txn_context_001",
        "txn_context_002",
    ]
    agent.invoke_async.assert_awaited_once()


def test_unknown_observation_transaction_ids_are_not_exposed(client):
    set_settings("configured-model")
    builder, _ = agent_builder(assessment(["unknown-transaction"]))
    app.dependency_overrides[get_risk_agent_builder] = lambda: builder

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["findings"][0]["rule_code"] == "HIGH_AMOUNT"
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_observations" not in response.json()


def test_agent_failure_preserves_deterministic_results(client):
    set_settings("configured-model")
    app.dependency_overrides[get_risk_agent_builder] = lambda: Mock(
        side_effect=RuntimeError("AWS credentials are invalid")
    )

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["findings"][0]["rule_code"] == "HIGH_AMOUNT"
    assert response.json()["ai_status"] == "unavailable"
    assert "AWS credentials are invalid" not in response.text


def test_missing_model_with_explicit_ai_request_returns_unavailable(client):
    set_settings(None)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["ai_status"] == "unavailable"
