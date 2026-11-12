# Risk Monitor — AWS Bedrock + Strands + AgentCore

A customer-owned risk-monitoring agent that accepts a batch of financial transactions, applies verified high-amount and velocity rules, and optionally uses AWS Bedrock through Strands for **advisory contextual observations**. Suspicious results can trigger a signed HTTPS `risk.detected` webhook.

This repository supports **local Docker Compose** and an **AWS Terraform/AgentCore deployment blueprint**. The cloud infrastructure was planned and validated, **not applied** in the supplied snapshot. See [Assessment coverage and limitations](#assessment-coverage-and-limitations) before presenting it as a deployed solution.

## What the application does

- **API:** `POST /api/v1/risk/analyze` locally, or `POST /invocations` inside AgentCore. Both reuse the same FastAPI handler and require `X-API-Key` and `Idempotency-Key`.
- **Verified risk findings:** deterministic `HIGH_AMOUNT` and `HIGH_VELOCITY` rules. Multi-currency thresholds and five-minute velocity detection are implemented in `app/services/risk_rules.py`.
- **Meaningful AI role:** Strands calls `get_validated_transactions` and `get_verified_risk_findings`. Bedrock returns a structured summary and *advisory*, evidence-linked observations. AI suggestions do **not** change verified rule results or prove fraud. AI is enabled by default when `BEDROCK_MODEL_ID` is configured; `?include_ai=false` opts out.
- **Idempotency:** DynamoDB stores request reservation, completed response and (when needed) webhook intent. A matching replay returns the saved response without calling Bedrock again; mismatched payloads or in-flight requests return `409`.
- **Webhook:** the validated event is persisted with the completed response, then signed using Standard Webhooks and sent to a configured HTTPS receiver. Claiming limits delivery to five attempts; undelivered events are retried only when the *same idempotent request* is replayed, not by a background worker.

### Quick reference

| Item | Value |
| --- | --- |
| Python | 3.13+ (`uv.lock` included) |
| Local API | `http://localhost:8000/api/v1/risk/analyze` |
| Local health | `GET http://localhost:8000/api/v1/health/` |
| AgentCore health | `GET /ping` on port 8080 |
| AgentCore invocation | `POST /invocations` on port 8080 |
| Required request headers | `X-API-Key`, `Idempotency-Key` (1–128 safe characters) |
| DynamoDB partition key | `pk` (`String`) |
| DynamoDB TTL attribute | `expires_at` (`Number`, Unix seconds) |
| Tested model (previous smoke run) | `amazon.nova-micro-v1:0` in `us-east-1` (access still must be checked per account) |

## 1. Run locally with Docker Compose

**Prerequisites:** Docker with Compose, an AWS account/profile authorized for Bedrock and DynamoDB, and a DynamoDB table matching the schema above. The configured model must be accessible in the chosen region. For SSO profiles, log in before launching Compose.

```bash
cp .env.example .env
# Edit .env: AWS_PROFILE, AWS_REGION, API_KEY, DYNAMODB_TABLE_NAME,
# BEDROCK_MODEL_ID; optionally enable the signed webhook.
aws sso login --profile your-profile  # only for SSO profiles
aws sts get-caller-identity --profile your-profile

docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8000/api/v1/health/
```

Compose mounts the host's `${HOME}/.aws` **read-only** at the non-root app user's home. Set `AWS_PROFILE` in `.env` to match your host profile; do not copy static AWS credentials into the image. `.env` is developer-only and excluded from Git and Docker builds. The container being **healthy** only confirms the HTTP service is running; it does not confirm Bedrock, DynamoDB or webhook connectivity.

### Local API smoke request

The example below uses synthetic data. Enter the same API key you configured in `.env` without committing it:

```bash
read -r -s -p 'Local API key: ' API_KEY; echo
export API_KEY
curl -fsS -X POST 'http://localhost:8000/api/v1/risk/analyze' \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -H 'Idempotency-Key: demo-risk-001' \
  --data-binary '{"transactions":[{"transaction_id":"demo-tx-001","customer_id":"demo-customer","amount":"25000.00","currency":"USD","merchant":"Demo Merchant","timestamp":"2026-11-12T10:00:00Z"}]}'
```

Expected behavior for this **high-amount** sample: a verified `HIGH_AMOUNT` finding; optional `ai_status` and AI observations if a configured Bedrock call succeeds. Repeat the **identical** request and key to confirm the stored response is replayed. Use a *new* `Idempotency-Key` when changing the payload or testing new configuration/prompt behavior; changing the transaction payload with the same key returns `409`.

To test contextual AI *without* deterministic findings, send three near-threshold same-currency transactions for one customer, separated by more than five minutes, with a new idempotency key. Observations are advisory and model-dependent, not a guaranteed detection outcome.

### Optional signed webhook

Set `WEBHOOK_ENABLED=true`, an HTTPS `WEBHOOK_URL` receiving Standard Webhooks, and a valid `WEBHOOK_SIGNING_SECRET=whsec_<base64-of-random-secret>` in `.env`. The receiver must verify the raw body against the `webhook-id`, `webhook-timestamp` and `webhook-signature` headers, enforce a timestamp tolerance, and deduplicate by stable `webhook-id`.

A notification is created when **verified findings or validated AI observations** exist. With no findings/observations, no webhook is sent. A receiver returning `2xx` marks delivery `DELIVERED`. A failed delivery is retained for a possible replay-triggered retry; there is **no autonomous retry worker**, and pending data shares the 24-hour completed-record TTL. Delivery is therefore **not guaranteed** if no replay occurs.

```bash
docker compose logs --tail=100 risk-monitor
docker compose down
```

Do not print or log webhook secrets, API keys or actual customer transaction data.

## 2. Deploy to AWS with Terraform + AgentCore Runtime

**Status:** Bootstrap and runtime-enabled Terraform **plans passed in the developer's report**; no `terraform apply` or live AgentCore invocation was performed in the provided snapshot. The commands below are a reproducible operator runbook, not a claim of a successful cloud deployment. **Terraform apply can incur AWS charges.**

### 2.1 Prerequisites and scope

- Terraform >=1.5, AWS provider constrained by `terraform/versions.tf` (`~> 6.71`), Docker Buildx, AWS CLI v2, an AWS profile with provisioning permissions, and `uv`/Python 3.13 for the SDK invocation example.
- Deploy **one separate stack per customer** (ideally a separate AWS account, role, DynamoDB table, ECR repository and secrets). If multiple stacks share an account, provide a distinct Terraform `name` and separate state for each.
- Confirm the Bedrock **model ID and IAM model/inference-profile ARN** in the chosen region. `bedrock_model_arn` must match what runtime model calls actually use.
- Use a properly protected Terraform backend for deployment. The example's default local state is suitable only for an isolated demonstration; do not share or commit `.tfstate`, `.tfvars`, secret material, or `.terraform/`.
- **MMDSv2 is mandatory for AgentCore invocations since June 30, 2026.** The Terraform provider version used for this project did not expose this field. Follow the explicit post-create verification below before invoking; plan success is insufficient.

```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
aws sts get-caller-identity
```

Create the **local, ignored** `terraform/terraform.tfvars` using **your real authorized model identifiers**, for example:

```hcl
aws_region       = "us-east-1"
name             = "risk-monitor-demo"
bedrock_model_id = "amazon.nova-micro-v1:0"
bedrock_model_arn = "REPLACE_WITH_AUTHORIZED_BEDROCK_MODEL_OR_INFERENCE_PROFILE_ARN"
webhook_enabled  = false
```

**Security limitation:** Current `webhook_url` Terraform variable is stored in Terraform state and passed into a runtime environment variable if enabled. Do **not** place a tokenized/private customer URL there; migrate it to Secrets Manager before using sensitive webhook destinations in production. Use `webhook_enabled=false` for the initial infrastructure smoke test.

### 2.2 Stage A — provision base AWS resources

The base plan has **six resources**: one on-demand DynamoDB table (`pk`, TTL `expires_at`), one immutable ECR repository with image scan-on-push, two **empty** Secrets Manager secrets, and AgentCore execution IAM role/policy. It does **not** yet create the runtime.

```bash
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check
terraform -chdir=terraform validate
terraform -chdir=terraform plan
# Review account, region, resources, cost, policies, and values first:
terraform -chdir=terraform apply
```

Set the API key secret value **outside Terraform** via AWS Secrets Manager Console (recommended for demo) or a secure AWS CLI workflow using a protected secret file. Never pass secret text directly as a shell command argument or `-var`, and never record it in Terraform state. The default configuration does not need the webhook signing secret until webhooks are enabled.

Retrieve useful Terraform outputs:

```bash
export ECR_URI="$(terraform -chdir=terraform output -raw ecr_repository_uri)"
export ECR_REPO="$(terraform -chdir=terraform output -raw ecr_repository_name)"
terraform -chdir=terraform output api_key_secret_arn
terraform -chdir=terraform output dynamodb_table_name
```

### 2.3 Stage B — build and push an immutable ARM64 image

```bash
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "${ECR_URI%%/*}"

# Use a fresh immutable tag on each build (a Git commit SHA works too).
export IMAGE_TAG="$(date -u +%Y%m%d%H%M%S)"
docker buildx build --platform linux/arm64 --push \
  -t "$ECR_URI:$IMAGE_TAG" .

export IMAGE_DIGEST="$(aws ecr describe-images \
  --repository-name "$ECR_REPO" --region "$AWS_REGION" \
  --image-ids "imageTag=$IMAGE_TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
test "$IMAGE_DIGEST" != 'None' && test -n "$IMAGE_DIGEST"
printf 'Image pushed: %s@%s\n' "$ECR_URI" "$IMAGE_DIGEST"
```

The Dockerfile serves AgentCore-compatible HTTP on **0.0.0.0:8080** using an ARM64 image. `GET /ping` returns `{"status":"Healthy"}` and `POST /invocations` uses the same risk handler as the local API. Compose separately runs port 8000.

### 2.4 Stage C — create AgentCore Runtime

```bash
terraform -chdir=terraform plan \
  -var='create_agentcore_runtime=true' \
  -var="image_uri=$ECR_URI@$IMAGE_DIGEST"

# Only after reviewing the plan and approving creation:
terraform -chdir=terraform apply \
  -var='create_agentcore_runtime=true' \
  -var="image_uri=$ECR_URI@$IMAGE_DIGEST"

export RUNTIME_ARN="$(terraform -chdir=terraform output -raw agentcore_runtime_arn)"
export RUNTIME_ID="${RUNTIME_ARN##*/}"
aws bedrock-agentcore-control get-agent-runtime \
  --region "$AWS_REGION" --agent-runtime-id "$RUNTIME_ID" \
  --query '{status:status,metadata:metadataConfiguration,role:roleArn}'
```

**Required MMDSv2 post-create gate.** AWS requires `metadataConfiguration.requireMMDSV2=true`; deployments without it can return `ValidationException`. With the pinned provider version, it is not managed by the Terraform resource. AWS `UpdateAgentRuntime` requires the current artifact and role—not just a metadata flag. **After reviewing the existing runtime configuration**, the following Boto3 command reads and preserves its managed settings while enabling MMDSv2:

```bash
uv run python - <<'PYMMDS'
import os
import boto3

client = boto3.client('bedrock-agentcore-control', region_name=os.environ['AWS_REGION'])
runtime_id = os.environ['RUNTIME_ID']
current = client.get_agent_runtime(agentRuntimeId=runtime_id)
if current.get('status') != 'READY':
    raise RuntimeError('AgentCore runtime is not READY')
args = {
    'agentRuntimeId': runtime_id,
    'agentRuntimeArtifact': current['agentRuntimeArtifact'],
    'roleArn': current['roleArn'],
    'metadataConfiguration': {'requireMMDSV2': True},
}
for field in (
    'networkConfiguration', 'protocolConfiguration',
    'requestHeaderConfiguration', 'environmentVariables',
    'lifecycleConfiguration',
):
    if current.get(field) is not None:
        args[field] = current[field]
client.update_agent_runtime(**args)
print('MMDSv2 update requested; verify READY status and MMDSv2 before invocation')
PYMMDS

aws bedrock-agentcore-control get-agent-runtime \
  --region "$AWS_REGION" --agent-runtime-id "$RUNTIME_ID" \
  --query '{status:status,requireMMDSV2:metadataConfiguration.requireMMDSV2}'
# Do NOT invoke unless status is READY and requireMMDSV2 is true.
```

This is a documented **operator workaround**, not a Terraform-managed setting. Review resulting resource settings after updates; prefer first-class Terraform configuration when a compatible provider adds the field.

Re-check MMDSv2 after any subsequent Terraform runtime update; manage it natively when the provider supports the field. No unattended cloud deployment/CI should be considered complete while this manual gate remains.

### 2.5 Invoke the AgentCore runtime with protected headers

AgentCore uses **AWS SigV4 invocation** and forwards only explicitly allowlisted `X-API-Key` and `Idempotency-Key` to this application. The normal `aws bedrock-agentcore invoke-agent-runtime` CLI command does not expose arbitrary custom headers; AWS documents a **Boto3 `before-sign` event handler** for this use case. The invoking principal also needs `bedrock-agentcore:InvokeAgentRuntime` permission on the runtime ARN. The runtime's execution IAM role is **not** the caller role.

After the runtime is READY and MMDSv2 is verified, set `RUNTIME_ARN`, `AWS_REGION`, your AWS profile and the API key. The following Python snippet uses synthetic transactions; **do not commit or share the key**:

```bash
read -r -s -p 'Runtime API key: ' API_KEY; echo
export API_KEY
export IDEMPOTENCY_KEY=agentcore-demo-001
uv run python - <<'PY'
import json
import os
import uuid
import boto3

client = boto3.client('bedrock-agentcore', region_name=os.environ['AWS_REGION'])

def add_headers(request, **kwargs):
    request.headers.add_header('X-API-Key', os.environ['API_KEY'])
    request.headers.add_header('Idempotency-Key', os.environ['IDEMPOTENCY_KEY'])

client.meta.events.register_first(
    'before-sign.bedrock-agentcore.InvokeAgentRuntime', add_headers
)
payload = {'transactions': [{
    'transaction_id': 'cloud-tx-001',
    'customer_id': 'demo-customer',
    'amount': '25000.00', 'currency': 'USD',
    'merchant': 'Demo Merchant',
    'timestamp': '2026-11-12T10:00:00Z',
}]}
response = client.invoke_agent_runtime(
    agentRuntimeArn=os.environ['RUNTIME_ARN'],
    runtimeSessionId=str(uuid.uuid4()),
    contentType='application/json',
    accept='application/json',
    payload=json.dumps(payload).encode('utf-8'),
)
try:
    print(response['response'].read().decode('utf-8'))
finally:
    response['response'].close()
PY
```

Repeat with the same key/payload to verify replay. Use a fresh key to test a changed request. For a full webhook smoke test, configure a real HTTPS receiver and valid Standard Webhooks signing secret, enable webhooks in Terraform, deploy a new runtime configuration, then verify **receiver acceptance, HMAC signature and DynamoDB delivery status**. This has **not** been independently run in the provided archive.

### 2.6 Redeploy and rollback

To release a new image: create a **new immutable tag/digest**, then run `terraform plan` and `apply` with `create_agentcore_runtime=true` and the new `image_uri`. Re-check runtime READY, MMDSv2, API response and webhook delivery. To roll back the image, apply the **previous known-good digest**, not a mutable `latest` tag.

**Prompt-versioning gap:** the current Strands prompt is in `app/services/risk_agent.py`, and `build_request_hash()` uses a fixed `analysis_version="1"`. There is **no customer-pinned prompt-version release mechanism yet**. A prompt-only change currently requires a new image and a careful idempotency/version strategy; do not claim automated customer-safe prompt rollout or false-positive rollback. This is part of the remaining assessment work.

## 3. Assessment coverage and limitations

| Original requirement | Current status |
| --- | --- |
| Accept transactions and return findings | **Implemented**, local API exercised in previous steps |
| Strands + Bedrock with meaningful AI | **Implemented**; synthetic live Bedrock call was reported before this deployment archive |
| External webhook on risk detection | **Implemented in the API**, HMAC sender and DynamoDB state tested; cloud receiver not verified |
| Docker container and local health | **Built and verified** in the previous developer run |
| GitHub Actions/GitLab pipeline: tests, image build **and deploy** | **Not present** in this archive |
| Prompt/config change through CI/CD to running deployment | **Not demonstrated** |
| Terraform customer-owned DynamoDB/ECR/IAM/secrets/runtime | **Plan/validation passed**, not applied; MMDSv2 post-create gate required |
| VPC layout, security groups, outbound Bedrock/webhook routes | **Design required**; Terraform currently uses `PUBLIC` network mode, not customer VPC mode |
| Secrets management | API key and signing secret fetched from Secrets Manager using runtime IAM; **webhook URL still in Terraform state/environment** |
| Two-customer isolation | One customer-owned stack/account per deployment is the chosen design; multi-customer shared-runtime isolation is **not** implemented |
| Prompt versions and safe rollback of false positives | Immutable image digests support code rollback; **prompt pinning/rollout policy still pending** |
| Webhook accessible only inside customer VPC | **Not implemented** in current public-network demo; needs VPC mode/private routing design and deployment |

### Operational and security boundaries

- **Do not claim exactly-once or guaranteed webhook delivery.** At most five claims are supported, but no background recovery scanner exists and completed records expire after ~24 hours. Receivers must deduplicate by `webhook-id`.
- **Do not infer fraud from AI alone.** AI observations are structured and linked to real transaction IDs, but they are advisory and may have false positives; deterministic findings remain independent.
- **No raw AWS access keys** belong in images or Terraform state. AgentCore uses its execution IAM role and MMDSv2; local Compose uses an existing AWS profile.
- **Cost and cleanup:** Terraform provisioning creates potentially billable resources. After verifying state, review with `terraform -chdir=terraform plan -destroy` before an explicitly approved destroy. ECR images and Secrets Manager deletion policies can affect cleanup timing.

## 4. Remaining work for assessment submission

1. Complete the **CI/CD pipeline**: test → build/push ARM64 digest → deploy/rollout with controlled AWS OIDC permissions; demonstrate a prompt/config update end-to-end.
2. Finish a concise **Day 2 architecture document** covering VPC/private endpoint routes, security groups, Secrets Manager including sensitive webhook URLs, least-privilege permissions, AgentCore onboarding, per-customer isolation, prompt pinning and rollback, and private webhook connectivity.
3. Execute and capture a **real AWS end-to-end smoke test** with DynamoDB, Bedrock and a signed HTTPS receiver after the MMDSv2 gate is satisfied.

### Official reference documentation

- [AgentCore HTTP service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)
- [AgentCore custom request headers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-header-allowlist.html)
- [AgentCore runtime troubleshooting / MMDSv2](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html)
- [Terraform AgentCore runtime resource](https://github.com/hashicorp/terraform-provider-aws/blob/main/website/docs/r/bedrockagentcore_agent_runtime.html.markdown)
