provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = var.name
      ManagedBy   = "terraform"
    }
  }
}
