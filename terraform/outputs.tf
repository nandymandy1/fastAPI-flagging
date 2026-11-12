output "dynamodb_table_name" {
  value = aws_dynamodb_table.idempotency.name
}

output "ecr_repository_uri" {
  value = aws_ecr_repository.app.repository_url
}

output "ecr_repository_name" {
  value = aws_ecr_repository.app.name
}

output "api_key_secret_arn" {
  value = aws_secretsmanager_secret.api_key.arn
}

output "webhook_signing_secret_arn" {
  value = aws_secretsmanager_secret.webhook_signing.arn
}

output "agentcore_runtime_arn" {
  value = try(aws_bedrockagentcore_agent_runtime.app[0].agent_runtime_arn, null)
}
