#!/bin/bash
# Generate self-signed certificate for staging HTTPS

set -e

echo "Generating self-signed certificate for staging environment..."

# Generate private key
openssl genrsa -out staging-private-key.pem 2048

# Generate certificate signing request
openssl req -new -key staging-private-key.pem -out staging-csr.pem -subj "/C=US/ST=State/L=City/O=Trazo Staging/CN=staging-alb-1273700937.us-east-2.elb.amazonaws.com"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in staging-csr.pem -signkey staging-private-key.pem -out staging-certificate.pem

# Upload to AWS Certificate Manager
echo "Uploading certificate to AWS Certificate Manager..."
CERT_ARN=$(aws acm import-certificate \
    --certificate fileb://staging-certificate.pem \
    --private-key fileb://staging-private-key.pem \
    --region us-east-2 \
    --query CertificateArn \
    --output text)

echo "Certificate uploaded successfully!"
echo "Certificate ARN: $CERT_ARN"
echo ""
echo "To use this certificate, add the following to your terraform.tfvars:"
echo "certificate_arn = \"$CERT_ARN\""

# Clean up local files
rm -f staging-private-key.pem staging-csr.pem staging-certificate.pem

echo "Local certificate files cleaned up."