import base64
from typing import Annotated
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config.config import Settings, get_settings
from app.dependencies import get_webhook_service
from app.services import WebhookService

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
URL = "https://webhooks.example.test/risk"


def test_disabled_webhook_returns_none_without_constructing_a_service(monkeypatch):
    service = Mock()
    monkeypatch.setattr("app.dependencies.WebhookService", service)

    result = get_webhook_service(
        Settings(_env_file=None, webhook_enabled=False, webhook_url=None)
    )

    assert result is None
    service.assert_not_called()


def test_enabled_webhook_returns_service_with_configured_url_and_secret():
    service = get_webhook_service(
        Settings(
            _env_file=None,
            webhook_enabled=True,
            webhook_url=URL,
            webhook_signing_secret=SECRET,
        )
    )

    assert isinstance(service, WebhookService)
    assert service.url == URL
    assert service.secret == SECRET
    assert service.client is None


@pytest.mark.parametrize("url", [None, "   "])
def test_enabled_webhook_requires_a_nonblank_url(url):
    with pytest.raises(HTTPException) as exc:
        get_webhook_service(
            Settings(
                _env_file=None,
                webhook_enabled=True,
                webhook_url=url,
                webhook_signing_secret=SECRET,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Webhook service unavailable"


@pytest.mark.parametrize("secret", [None, "   "])
def test_enabled_webhook_requires_a_nonblank_secret(secret):
    with pytest.raises(HTTPException) as exc:
        get_webhook_service(
            Settings(
                _env_file=None,
                webhook_enabled=True,
                webhook_url=URL,
                webhook_signing_secret=secret,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Webhook service unavailable"


def test_invalid_url_is_a_sanitized_service_unavailable_error():
    invalid_url = "http://internal.example.test/risk"

    with pytest.raises(HTTPException) as exc:
        get_webhook_service(
            Settings(
                _env_file=None,
                webhook_enabled=True,
                webhook_url=invalid_url,
                webhook_signing_secret=SECRET,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Webhook service unavailable"
    assert invalid_url not in str(exc.value.detail)
    assert SECRET not in str(exc.value.detail)


def test_dependency_resolves_enabled_webhook_without_delivery():
    test_app = FastAPI()
    test_app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        webhook_enabled=True,
        webhook_url=URL,
        webhook_signing_secret=SECRET,
    )

    @test_app.get("/webhook")
    def webhook(
        service: Annotated[WebhookService, Depends(get_webhook_service)],
    ) -> dict[str, str]:
        return {"url": service.url}

    response = TestClient(test_app).get("/webhook")

    assert response.status_code == 200
    assert response.json() == {"url": URL}


def test_dependency_returns_sanitized_503_for_invalid_configuration():
    test_app = FastAPI()
    test_app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        webhook_enabled=True,
        webhook_url="https://webhooks.example.test/risk#fragment",
        webhook_signing_secret=SECRET,
    )

    @test_app.get("/webhook")
    def webhook(
        _: Annotated[WebhookService, Depends(get_webhook_service)],
    ) -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(test_app).get("/webhook")

    assert response.status_code == 503
    assert response.json() == {"detail": "Webhook service unavailable"}
    assert SECRET not in response.text
