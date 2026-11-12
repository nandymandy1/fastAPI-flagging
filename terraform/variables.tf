variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "risk-monitor"
}

variable "bedrock_model_id" {
  type = string
}

variable "bedrock_model_arn" {
  type = string
}

variable "webhook_enabled" {
  type    = bool
  default = false
}

variable "webhook_url" {
  type    = string
  default = null
}

variable "image_uri" {
  type    = string
  default = ""
}

variable "create_agentcore_runtime" {
  type    = bool
  default = false
}
