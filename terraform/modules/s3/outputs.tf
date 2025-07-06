output "media_bucket_regional_domain" {
  value = aws_s3_bucket.media.bucket_regional_domain_name
}

output "media_bucket_id" {
  value = aws_s3_bucket.media.id
}

output "media_bucket_arn" {
  description = "ARN of the S3 media bucket"
  value       = aws_s3_bucket.media.arn
}
