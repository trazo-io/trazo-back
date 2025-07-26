resource "aws_s3_bucket" "media" {
  bucket = "${var.environment}-trazo-media-${data.aws_caller_identity.current.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE"]
    allowed_origins = var.environment == "staging" ? [
      "https://${var.domain_name}",
      "http://${var.domain_name}",
      "https://app-staging.trazo.io",
      "http://app-staging.trazo.io",
      "http://localhost:3000",
      "http://localhost:3001"
    ] : ["https://${var.domain_name}"]
    expose_headers  = ["ETag", "Content-Type", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_policy" "media" {
  count = var.cf_oai_arn != null ? 1 : 0
  
  bucket = aws_s3_bucket.media.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.cf_oai_arn
        }
        Action = "s3:GetObject"
        Resource = "${aws_s3_bucket.media.arn}/*"
      }
    ]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    
    filter {
      prefix = ""
    }
    
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

data "aws_caller_identity" "current" {}

# Enable versioning for media files (optional, helps with recovery)
resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  
  versioning_configuration {
    status = var.environment == "prod" ? "Enabled" : "Suspended"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
} 