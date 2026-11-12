from typing import Any
from time import time
from uuid import uuid4

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

MAX_WEBHOOK_ATTEMPTS = 5


class IdempotencyStoreError(RuntimeError):
    pass


class IdempotencyStore:
    def __init__(self, table):
        self.table = table

    def reserve(self, key: str, request_hash: str) -> dict | None:
        now = int(time())
        reservation = {
            "pk": key,
            "request_hash": request_hash,
            "status": "PROCESSING",
            "reservation_id": str(uuid4()),
            "event_id": str(uuid4()),
            "expires_at": now + 600,
        }
        try:
            self.table.put_item(
                Item=reservation,
                ConditionExpression=Attr("pk").not_exists()
                | Attr("expires_at").lte(now),
            )
        except ClientError as exc:
            if _is_conditional_failure(exc):
                if self.get(key):
                    return None
                raise IdempotencyStoreError("Idempotency reservation conflict") from exc
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        return reservation

    def get(self, key: str) -> dict | None:
        try:
            item = self.table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        return item if item and item.get("expires_at", 0) > int(time()) else None

    def complete(
        self,
        key: str,
        reservation_id: str,
        response: dict,
        webhook_event: dict | None = None,
    ) -> None:
        event_id = (
            webhook_event.get("event_id") if isinstance(webhook_event, dict) else None
        )
        if webhook_event is not None and (
            not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128
        ):
            raise IdempotencyStoreError("Idempotency webhook event is invalid")

        now = int(time())
        update_expression = (
            "SET #status = :completed, response = :response, expires_at = :expires"
        )
        condition = (
            Attr("reservation_id").eq(reservation_id)
            & Attr("status").eq("PROCESSING")
            & Attr("expires_at").gt(now)
        )
        values: dict[str, dict[Any, Any] | int | str] = {
            ":completed": "COMPLETED",
            ":response": response,
            ":expires": now + 86400,
        }
        if webhook_event is not None:
            update_expression += ", webhook = :webhook"
            condition &= Attr("event_id").eq(event_id)
            values[":webhook"] = {
                "status": "PENDING",
                "event": webhook_event,
                "attempts": 0,
            }

        try:
            self.table.update_item(
                Key={"pk": key},
                UpdateExpression=update_expression,
                ConditionExpression=condition,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=values,
            )
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency completion failed") from exc

    def release(self, key: str, reservation_id: str) -> None:
        try:
            self.table.delete_item(
                Key={"pk": key},
                ConditionExpression=(
                    Attr("reservation_id").eq(reservation_id)
                    & Attr("status").eq("PROCESSING")
                ),
            )
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency release failed") from exc

    def claim_webhook(self, key: str) -> dict | None:
        now = int(time())
        claim_id = str(uuid4())
        claimable = Attr("webhook.status").is_in(["PENDING", "FAILED"]) | (
            Attr("webhook.status").eq("DELIVERING")
            & Attr("webhook.claim_expires_at").lte(now)
        )
        try:
            result = self.table.update_item(
                Key={"pk": key},
                UpdateExpression=(
                    "SET webhook.#webhook_status = :delivering, "
                    "webhook.claim_id = :claim_id, "
                    "webhook.claim_expires_at = :claim_expires_at, "
                    "webhook.attempts = webhook.attempts + :one"
                ),
                ConditionExpression=(
                    Attr("status").eq("COMPLETED")
                    & Attr("expires_at").gt(now)
                    & Attr("webhook.attempts").lt(MAX_WEBHOOK_ATTEMPTS)
                    & claimable
                ),
                ExpressionAttributeNames={"#webhook_status": "status"},
                ExpressionAttributeValues={
                    ":delivering": "DELIVERING",
                    ":claim_id": claim_id,
                    ":claim_expires_at": now + 60,
                    ":one": 1,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return None
            raise IdempotencyStoreError("Webhook claim failed") from exc
        except Exception as exc:
            raise IdempotencyStoreError("Webhook claim failed") from exc

        webhook = result.get("Attributes", {}).get("webhook")
        if not isinstance(webhook, dict):
            raise IdempotencyStoreError("Webhook claim failed")
        return webhook

    def mark_webhook_delivered(self, key: str, claim_id: str) -> None:
        self._update_webhook_status(key, claim_id, "DELIVERED")

    def mark_webhook_failed(self, key: str, claim_id: str) -> None:
        self._update_webhook_status(key, claim_id, "FAILED")

    def _update_webhook_status(self, key: str, claim_id: str, status: str) -> None:
        now = int(time())
        try:
            self.table.update_item(
                Key={"pk": key},
                UpdateExpression=(
                    "SET webhook.#webhook_status = :webhook_status "
                    "REMOVE webhook.claim_id, webhook.claim_expires_at"
                ),
                ConditionExpression=(
                    Attr("status").eq("COMPLETED")
                    & Attr("webhook.status").eq("DELIVERING")
                    & Attr("webhook.claim_id").eq(claim_id)
                    & Attr("expires_at").gt(now)
                ),
                ExpressionAttributeNames={"#webhook_status": "status"},
                ExpressionAttributeValues={":webhook_status": status},
            )
        except Exception as exc:
            raise IdempotencyStoreError("Webhook delivery state update failed") from exc


def _is_conditional_failure(exc: ClientError) -> bool:
    return (
        exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    )
