# Risk Monitor

## Local Docker setup

Required: Docker Compose, an AWS profile with Bedrock and DynamoDB permissions, and a
customer-owned DynamoDB table in `AWS_REGION`. The table partition key must be `pk`
(String) and its TTL attribute must be `expires_at` (Number).

Create local configuration and authenticate with your normal AWS profile:

```bash
cp .env.example .env
aws sso login --profile default # only when your profile uses AWS IAM Identity Center
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8000/api/v1/health/
```

Set the real `AWS_PROFILE`, `BEDROCK_MODEL_ID`, `API_KEY`, and
`DYNAMODB_TABLE_NAME` in `.env`. The container mounts `~/.aws` read-only for the
non-root application user; it does not contain credentials. `.env` is for local
demonstration only—cloud deployment should use IAM roles and managed secrets.

Submit a synthetic suspicious transaction:

```bash
export API_KEY='the-same-value-configured-in-.env'
curl -sS -X POST http://localhost:8000/api/v1/risk/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: demo-risk-001" \
  -d '{"transactions":[{"transaction_id":"demo-001","customer_id":"demo-customer","amount":"25000.00","currency":"USD","merchant":"Demo Merchant","timestamp":"2026-11-12T10:00:00Z"}]}'
```

Use the same `Idempotency-Key` again to replay the saved response without rerunning
analysis. To receive a signed webhook, set `WEBHOOK_ENABLED=true`, configure an HTTPS
`WEBHOOK_URL`, and provide a valid `WEBHOOK_SIGNING_SECRET`; the receiver gets a
`risk.detected` event only for deterministic findings or validated AI observations.

Stop the local stack with:

```bash
docker compose down
```
