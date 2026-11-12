import asyncio
import base64
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from standardwebhooks.webhooks import Webhook

from app.schemas.webhook import RiskWebhookEventDto
from app.services import WebhookDeliveryError, WebhookService

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
URL = "https://webhooks.example.test/risk"


@pytest.fixture
def event() -> RiskWebhookEventDto:
    return RiskWebhookEventDto.model_validate(
        {
            "event_id": "event_001",
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
                        "reason": "Synthetic high amount finding",
                        "transaction_id": "txn-001",
                        "risk_level": "high",
                        "rule_code": "HIGH_AMOUNT",
                    }
                ],
            },
        }
    )


def client(handler, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


def close(http_client: httpx.AsyncClient) -> None:
    asyncio.run(http_client.aclose())


def test_successful_delivery_posts_once_to_configured_url(event):
    requests = []
    http_client = client(
        lambda request: requests.append(request) or httpx.Response(200)
    )
    service = WebhookService(URL, SECRET, http_client)

    asyncio.run(service.send(event))
    close(http_client)

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == URL


@pytest.mark.parametrize("status_code", [201])
def test_other_2xx_responses_are_acknowledged(event, status_code):
    http_client = client(lambda _: httpx.Response(status_code))

    asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)


def test_transmitted_body_and_headers_have_a_valid_hmac_signature(event):
    requests = []
    http_client = client(
        lambda request: requests.append(request) or httpx.Response(200)
    )

    asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)

    request = requests[0]
    headers = dict(request.headers)
    assert headers["webhook-id"] == event.event_id
    assert headers["webhook-timestamp"]
    assert headers["webhook-signature"]
    assert headers["content-type"] == "application/json"
    assert request.content == event.model_dump_json().encode("utf-8")
    assert Webhook(SECRET).verify(request.content, headers) == event.model_dump(
        mode="json"
    )


def test_redirects_are_not_followed_even_with_an_injected_redirecting_client(event):
    requests = []
    http_client = client(
        lambda request: (
            requests.append(request)
            or httpx.Response(302, headers={"Location": "https://other.example.test"})
        ),
        follow_redirects=True,
    )

    with pytest.raises(WebhookDeliveryError):
        asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)

    assert len(requests) == 1


@pytest.mark.parametrize("status_code", [400, 500])
def test_non_2xx_responses_fail_without_retries(event, status_code):
    requests = []
    http_client = client(
        lambda request: requests.append(request) or httpx.Response(status_code)
    )

    with pytest.raises(WebhookDeliveryError, match="not acknowledged"):
        asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)

    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout])
def test_network_errors_and_timeouts_are_sanitized(event, error):
    requests = []

    def fail(request):
        requests.append(request)
        raise error("sensitive transport failure", request=request)

    http_client = client(fail)
    service = WebhookService(URL, SECRET, http_client)

    with pytest.raises(WebhookDeliveryError, match="Webhook delivery failed") as exc:
        asyncio.run(service.send(event))
    close(http_client)

    assert len(requests) == 1
    assert "sensitive transport failure" not in str(exc.value)
    assert SECRET not in str(exc.value)


def test_delivery_uses_a_five_second_request_timeout(event):
    timeouts = []

    def capture_timeout(request):
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200)

    http_client = client(capture_timeout)

    asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)

    assert set(timeouts[0].values()) == {5.0}


@pytest.mark.parametrize(
    "url",
    [
        "http://webhooks.example.test/risk",
        "https://user:password@webhooks.example.test/risk",
    ],
)
def test_invalid_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        WebhookService(url, SECRET)


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "not-a-webhook-secret",
        "whsec_not base64!",
    ],
)
def test_invalid_secrets_are_rejected_before_any_http_request(secret):
    http_client = Mock()

    with pytest.raises(ValueError):
        WebhookService(URL, secret, http_client)

    http_client.post.assert_not_called()


def test_failure_messages_do_not_expose_secret_body_or_response_body(event):
    response_body = "sensitive receiver response"
    http_client = client(lambda _: httpx.Response(500, text=response_body))

    with pytest.raises(WebhookDeliveryError) as exc:
        asyncio.run(WebhookService(URL, SECRET, http_client).send(event))
    close(http_client)

    assert SECRET not in str(exc.value)
    assert event.model_dump_json() not in str(exc.value)
    assert response_body not in str(exc.value)
