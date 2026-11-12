data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  agentcore_name = replace(var.name, "-", "_")
}

resource "aws_dynamodb_table" "idempotency" {
  name         = "${var.name}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_secretsmanager_secret" "api_key" {
  name = "${var.name}/api-key"
}

resource "aws_secretsmanager_secret" "webhook_signing" {
  name = "${var.name}/webhook-signing-secret"
}

data "aws_iam_policy_document" "runtime_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:runtime/*"
      ]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name               = "${var.name}-agentcore-runtime"
  assume_role_policy = data.aws_iam_policy_document.runtime_assume_role.json
}

data "aws_iam_policy_document" "runtime" {
  statement {
    sid = "ReadRuntimeImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid       = "GetEcrAuthorizationToken"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "IdempotencyTable"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.idempotency.arn]
  }

  statement {
    sid       = "ReadApplicationSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.api_key.arn, aws_secretsmanager_secret.webhook_signing.arn]
  }

  statement {
    sid = "InvokeConfiguredModel"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [var.bedrock_model_arn]
  }

  statement {
    sid = "AgentCoreLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "runtime" {
  name   = "${var.name}-runtime"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "app" {
  count = var.create_agentcore_runtime ? 1 : 0

  agent_runtime_name = local.agentcore_name
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.image_uri
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  request_header_configuration {
    request_header_allowlist = ["X-API-Key", "Idempotency-Key"]
  }

  environment_variables = merge(
    {
      APP_ENV             = "production"
      AWS_REGION          = var.aws_region
      API_KEY_SECRET_ARN  = aws_secretsmanager_secret.api_key.arn
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.idempotency.name
      WEBHOOK_ENABLED     = tostring(var.webhook_enabled)
    },
    var.webhook_enabled ? {
      WEBHOOK_SIGNING_SECRET_ARN = aws_secretsmanager_secret.webhook_signing.arn
      WEBHOOK_URL                = var.webhook_url
    } : {},
  )

  lifecycle {
    precondition {
      condition     = trimspace(var.image_uri) != ""
      error_message = "Set image_uri to an immutable ECR image URI or digest before creating the runtime."
    }

    precondition {
      condition     = !var.webhook_enabled || (var.webhook_url != null && trimspace(var.webhook_url) != "")
      error_message = "Set webhook_url when webhook_enabled is true."
    }
  }
}
