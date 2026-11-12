import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from standardwebhooks.webhooks import Webhook

import app.api.risk as risk_api
from app.dependencies import (
    get_idempotency_store,
    get_risk_agent_builder,
    get_risk_analysis_service,
    get_webhook_service,
    require_api_key,
)
from app.main import app
from app.schemas.risk import AiAssessmentDto
from app.services.risk_analysis import RiskAnalysisService
from app.services.webhook import WebhookService

WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
WEBHOOK_URL = "https://webhooks.example.test/risk"

PAYLOAD = {
    "transactions": [
        {
            "transaction_id": "idempotency_txn_001",
            "customer_id": "customer_001",
            "amount": "25000.00",
            "currency": "USD",
            "merchant": "Test Merchant",
            "timestamp": "2026-11-11T10:00:00Z",
        }
    ]
}


class FakeStore:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.fail_get = False
        self.fail_complete = False
        self.race_response = None

    def get(self, key):
        self.calls.append("get")
        if self.fail_get:
            raise RuntimeError("DynamoDB unavailable")
        return self.records.get(key)

    def reserve(self, key, request_hash):
        self.calls.append("reserve")
        if self.race_response:
            self.records[key] = {
                "request_hash": request_hash,
                "status": "COMPLETED",
                "response": self.race_response,
            }
            return None
        if key in self.records:
            return None
        reservation = {
            "pk": key,
            "request_hash": request_hash,
            "status": "PROCESSING",
            "reservation_id": "reservation-1",
            "event_id": "event-1",
        }
        self.records[key] = reservation
        return reservation

    def complete(self, key, reservation_id, response, webhook_event=None):
        self.calls.append("complete")
        if self.fail_complete:
            raise RuntimeError("DynamoDB unavailable")
        record = self.records[key]
        if record["reservation_id"] != reservation_id:
            raise RuntimeError("Reservation ownership lost")
        record.update(status="COMPLETED", response=response)
        if webhook_event is not None:
            record["webhook"] = {
                "status": "PENDING",
                "event": webhook_event,
                "attempts": 0,
            }

    def release(self, key, reservation_id):
        self.calls.append("release")
        record = self.records.get(key)
        if record and record["reservation_id"] == reservation_id:
            del self.records[key]

    def claim_webhook(self, key):
        record = self.records.get(key)
        webhook = record and record.get("webhook")
        if not webhook or webhook["status"] not in {"PENDING", "FAILED"}:
            return None
        webhook["status"] = "DELIVERING"
        webhook["attempts"] += 1
        webhook["claim_id"] = f"claim-{webhook['attempts']}"
        return webhook

    def mark_webhook_delivered(self, key, claim_id):
        webhook = self.records[key]["webhook"]
        if webhook.get("claim_id") != claim_id:
            raise RuntimeError("Claim ownership lost")
        webhook["status"] = "DELIVERED"

    def mark_webhook_failed(self, key, claim_id):
        webhook = self.records[key]["webhook"]
        if webhook.get("claim_id") != claim_id:
            raise RuntimeError("Claim ownership lost")
        webhook["status"] = "FAILED"


@pytest.fixture
def client_and_store():
    overrides = app.dependency_overrides.copy()
    store = FakeStore()
    app.dependency_overrides.clear()
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_idempotency_store] = lambda: store
    app.dependency_overrides[get_webhook_service] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides)


def post(client, key="request-1", payload=PAYLOAD):
    return client.post(
        "/api/v1/risk/analyze",
        json=payload,
        headers={"Idempotency-Key": key},
    )


def webhook_service(status_code=200):
    requests = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(status_code)
        )
    )
    return WebhookService(WEBHOOK_URL, WEBHOOK_SECRET, client), requests, client


def test_first_request_analyzes_and_persists_response(client_and_store):
    client, store = client_and_store

    response = post(client)

    assert response.status_code == 200
    assert store.records["request-1"]["status"] == "COMPLETED"
    assert store.records["request-1"]["response"] == response.json()


def test_completed_request_replays_without_reanalysis(client_and_store):
    client, store = client_and_store
    webhook, requests, http_client = webhook_service()
    service = Mock(wraps=RiskAnalysisService())
    result = MagicMock()
    result.stop_reason = "end_turn"
    result.metrics.tool_metrics = {
        name: SimpleNamespace(success_count=1, error_count=0)
        for name in ("get_verified_risk_findings", "get_validated_transactions")
    }
    result.structured_output = AiAssessmentDto(
        ai_summary="Verified finding.", ai_observations=[]
    )
    agent = Mock(invoke_async=AsyncMock(return_value=result))
    agent_builder = Mock(return_value=agent)
    app.dependency_overrides[get_risk_analysis_service] = lambda: service
    app.dependency_overrides[get_risk_agent_builder] = lambda: agent_builder
    app.dependency_overrides[get_webhook_service] = lambda: webhook

    first = client.post(
        "/api/v1/risk/analyze?include_ai=true",
        json=PAYLOAD,
        headers={"Idempotency-Key": "request-1"},
    )
    second = client.post(
        "/api/v1/risk/analyze?include_ai=true",
        json=PAYLOAD,
        headers={"Idempotency-Key": "request-1"},
    )
    asyncio.run(http_client.aclose())

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert service.analyze.call_count == 1
    agent.invoke_async.assert_awaited_once()
    assert store.calls.count("complete") == 1
    assert store.records["request-1"]["webhook"]["status"] == "DELIVERED"
    assert len(requests) == 1


def test_deterministic_risk_persists_and_delivers_a_signed_webhook(client_and_store):
    client, store = client_and_store
    service, requests, http_client = webhook_service()
    app.dependency_overrides[get_webhook_service] = lambda: service

    response = post(client)
    asyncio.run(http_client.aclose())

    assert response.status_code == 200
    assert store.records["request-1"]["webhook"]["status"] == "DELIVERED"
    assert len(requests) == 1
    event = Webhook(WEBHOOK_SECRET).verify(
        requests[0].content, dict(requests[0].headers)
    )
    assert event["event_id"] == "event-1"
    assert event["data"]["findings"][0]["rule_code"] == "HIGH_AMOUNT"


def test_ai_only_observation_delivers_an_advisory_webhook(client_and_store):
    client, store = client_and_store
    service, requests, http_client = webhook_service()
    app.dependency_overrides[get_webhook_service] = lambda: service
    result = MagicMock(
        stop_reason="end_turn",
        structured_output=AiAssessmentDto(
            ai_summary="Related payments require review.",
            ai_observations=[
                {
                    "pattern": "possible_split_payments",
                    "transaction_ids": ["txn_001", "txn_002"],
                    "explanation": "Two related near-threshold payments.",
                    "status": "review",
                }
            ],
        ),
    )
    result.metrics.tool_metrics = {
        name: SimpleNamespace(success_count=1, error_count=0)
        for name in ("get_verified_risk_findings", "get_validated_transactions")
    }
    app.dependency_overrides[get_risk_agent_builder] = lambda: Mock(
        return_value=Mock(invoke_async=AsyncMock(return_value=result))
    )
    payload = {
        "transactions": [
            {
                **PAYLOAD["transactions"][0],
                "transaction_id": "txn_001",
                "amount": "4900.00",
            },
            {
                **PAYLOAD["transactions"][0],
                "transaction_id": "txn_002",
                "amount": "4900.00",
            },
        ]
    }

    response = post(client, payload=payload)
    asyncio.run(http_client.aclose())

    assert response.status_code == 200
    assert response.json()["findings"] == []
    assert store.records["request-1"]["webhook"]["status"] == "DELIVERED"
    event = Webhook(WEBHOOK_SECRET).verify(
        requests[0].content, dict(requests[0].headers)
    )
    assert event["data"]["findings"] == []
    assert event["data"]["ai_observations"][0]["status"] == "review"


def test_no_risk_does_not_create_or_send_a_webhook(client_and_store):
    client, store = client_and_store
    service, requests, http_client = webhook_service()
    app.dependency_overrides[get_webhook_service] = lambda: service
    payload = {"transactions": [{**PAYLOAD["transactions"][0], "amount": "100.00"}]}

    response = post(client, payload=payload)
    asyncio.run(http_client.aclose())

    assert response.status_code == 200
    assert "webhook" not in store.records["request-1"]
    assert requests == []


def test_webhook_failure_keeps_completed_analysis_and_marks_failed(client_and_store):
    client, store = client_and_store
    service, _, http_client = webhook_service(500)
    app.dependency_overrides[get_webhook_service] = lambda: service

    response = post(client)
    asyncio.run(http_client.aclose())

    assert response.status_code == 200
    assert response.json()["findings"][0]["rule_code"] == "HIGH_AMOUNT"
    assert store.records["request-1"]["status"] == "COMPLETED"
    assert store.records["request-1"]["webhook"]["status"] == "FAILED"


def test_same_key_with_different_payload_returns_conflict(client_and_store):
    client, _ = client_and_store
    changed_payload = {
        **PAYLOAD,
        "transactions": [{**PAYLOAD["transactions"][0], "amount": "100.00"}],
    }

    assert post(client).status_code == 200
    response = post(client, payload=changed_payload)

    assert response.status_code == 409


def test_reservation_race_rereads_completed_response(client_and_store):
    client, store = client_and_store
    service = Mock(wraps=RiskAnalysisService())
    store.race_response = {
        "status": "completed",
        "summary": {
            "total_findings": 0,
            "total_transactions": 1,
            "flagged_transactions": 0,
        },
        "findings": [],
    }
    app.dependency_overrides[get_risk_analysis_service] = lambda: service

    response = post(client)

    assert response.status_code == 200
    assert response.json() == store.race_response
    service.analyze.assert_not_called()


def test_invalid_idempotency_key_returns_bad_request(client_and_store):
    client, _ = client_and_store

    response = client.post(
        "/api/v1/risk/analyze",
        json=PAYLOAD,
        headers={"Idempotency-Key": "invalid key"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_missing_store_fails_closed_without_analysis(client_and_store):
    client, _ = client_and_store
    service = Mock(wraps=RiskAnalysisService())
    app.dependency_overrides[get_idempotency_store] = lambda: None
    app.dependency_overrides[get_risk_analysis_service] = lambda: service

    response = post(client)

    assert response.status_code == 503
    service.analyze.assert_not_called()


def test_store_error_fails_closed_without_analysis(client_and_store):
    client, store = client_and_store
    service = Mock(wraps=RiskAnalysisService())
    store.fail_get = True
    app.dependency_overrides[get_risk_analysis_service] = lambda: service

    response = post(client)

    assert response.status_code == 503
    assert "DynamoDB unavailable" not in response.text
    service.analyze.assert_not_called()


def test_completion_failure_does_not_return_success(client_and_store):
    client, store = client_and_store
    store.fail_complete = True

    response = post(client)

    assert response.status_code == 503
    assert "DynamoDB unavailable" not in response.text


def test_blocking_store_operations_are_offloaded(client_and_store, monkeypatch):
    client, _ = client_and_store
    calls = []

    async def run_in_thread(function, *args):
        calls.append(function.__name__)
        return function(*args)

    monkeypatch.setattr(risk_api.asyncio, "to_thread", run_in_thread)

    assert post(client, key="success").status_code == 200

    def fail_analysis(_):
        raise RuntimeError("analysis failed")

    app.dependency_overrides[get_risk_analysis_service] = lambda: Mock(
        analyze=fail_analysis
    )
    response = post(client, key="failure")

    assert response.status_code == 500
    assert {"get", "reserve", "complete", "release"} <= set(calls)
