from urllib.parse import urlsplit

import httpx

from app.schemas.webhook import RiskWebhookEventDto
from app.utils import sign_webhook


class WebhookDeliveryError(Exception):
    pass


class WebhookService:
    def __init__(
        self,
        url: str,
        secret: str,
        client: httpx.AsyncClient | None = None,
    ):
        destination = urlsplit(url)
        if (
            destination.scheme != "https"
            or not destination.hostname
            or destination.username
            or destination.password
            or destination.fragment
        ):
            raise ValueError("Webhook URL must be an HTTPS URL without credentials")
        if not secret or not secret.strip():
            raise ValueError("Webhook secret must not be blank")

        self.url = url
        self.secret = secret
        self.client = client

    async def send(self, event: RiskWebhookEventDto) -> None:
        body, headers = sign_webhook(event, self.secret)

        if self.client:
            await self._post(self.client, body, headers)
            return

        async with httpx.AsyncClient(
            timeout=5.0, follow_redirects=False, verify=True
        ) as client:
            await self._post(client, body, headers)

    async def _post(
        self, client: httpx.AsyncClient, body: bytes, headers: dict[str, str]
    ) -> None:
        try:
            response = await client.post(
                self.url,
                content=body,
                headers=headers,
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError("Webhook delivery failed") from exc

        if not response.is_success:
            raise WebhookDeliveryError("Webhook delivery was not acknowledged")
