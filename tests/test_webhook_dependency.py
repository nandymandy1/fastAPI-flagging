import base64
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.config.config import Settings
from app.dependencies import get_webhook_service
from app.services import WebhookService

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
URL = "https://webhooks.example.test/risk"


def test_disabled_webhook_returns_none_without_constructing_a_service(monkeypatch):
    service = Mock()
    monkeypatch.setattr("app.dependencies.WebhookService", service)

    assert get_webhook_service(Settings(_env_file=None)) is None
    service.assert_not_called()


def test_enabled_webhook_returns_configured_service_without_delivery():
    service = get_webhook_service(
        Settings(
            _env_file=None,
            webhook_enabled=True,
            webhook_url=URL,
            webhook_signing_secret=SECRET,
        )
    )

    assert isinstance(service, WebhookService)
    assert (service.url, service.secret, service.client) == (URL, SECRET, None)


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        (None, SECRET),
        ("http://webhooks.example.test/risk", SECRET),
        (URL, "whsec_not base64!"),
    ],
)
def test_invalid_enabled_webhook_configuration_is_sanitized(url, secret):
    with pytest.raises(HTTPException) as exc:
        get_webhook_service(
            Settings(
                _env_file=None,
                webhook_enabled=True,
                webhook_url=url,
                webhook_signing_secret=secret,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Webhook service unavailable"
    assert SECRET not in str(exc.value.detail)
