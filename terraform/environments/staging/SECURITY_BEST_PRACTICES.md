# Staging Environment Security Best Practices

## Current Security Status ⚠️

### Issues to Address:
1. **No SSL Certificate** - Currently running HTTP only
2. **Security Headers Disabled** - CSRF, Session cookies not secure
3. **Potential Data Exposure** - Without HTTPS, all data is transmitted in plain text

## Recommended Security Configuration

### 1. **ALWAYS Use HTTPS in Staging** 🔒
```bash
# Option A: Self-signed certificate (immediate, free)
./generate-self-signed-cert.sh

# Option B: Let's Encrypt via AWS Certificate Manager (recommended)
# Request a free SSL certificate through AWS ACM for your staging domain

# Option C: Use AWS CloudFront with ACM certificate (best for cost)
# CloudFront provides free SSL termination
```

### 2. **NEVER Enable DEBUG=True** ❌
```python
# WRONG - Exposes sensitive data
DEBUG = True  # NEVER do this in staging/production

# CORRECT - Always keep debug disabled
DEBUG = False
```

### 3. **Proper Django Settings Structure** ✅
```
settings/
├── base.py       # Common settings
├── dev.py        # Local development (DEBUG=True OK here)
├── staging.py    # Staging-specific (DEBUG=False)
└── prod.py       # Production (DEBUG=False)
```

### 4. **Environment-Specific Configuration**
```terraform
# terraform.tfvars for staging
environment_variables = {
  DJANGO_SETTINGS_MODULE = "backend.settings.staging"  # Use staging settings
  SECURE_SSL_REDIRECT    = "True"   # Enable after SSL cert
  SESSION_COOKIE_SECURE  = "True"   # Enable after SSL cert
  CSRF_COOKIE_SECURE     = "True"   # Enable after SSL cert
}
```

### 5. **Security Headers Checklist** ✓
- [ ] SSL Certificate installed
- [ ] SECURE_SSL_REDIRECT = True
- [ ] SESSION_COOKIE_SECURE = True
- [ ] CSRF_COOKIE_SECURE = True
- [ ] SECURE_HSTS_SECONDS > 0
- [ ] SECURE_CONTENT_TYPE_NOSNIFF = True
- [ ] SECURE_BROWSER_XSS_FILTER = True
- [ ] X_FRAME_OPTIONS = 'DENY'

## Implementation Steps

### Step 1: Generate SSL Certificate
```bash
# Run the provided script
cd terraform/environments/staging
./generate-self-signed-cert.sh
```

### Step 2: Update Terraform Configuration
```hcl
# In terraform.tfvars
certificate_arn = "arn:aws:acm:us-east-2:xxx:certificate/xxx"
```

### Step 3: Enable Security Headers
```hcl
# Update task definition environment variables
{ name = "SECURE_SSL_REDIRECT", value = "True" }
{ name = "SESSION_COOKIE_SECURE", value = "True" }
{ name = "CSRF_COOKIE_SECURE", value = "True" }
```

### Step 4: Deploy Changes
```bash
terraform apply
```

## Why This Matters

### Security Risks of Current Setup:
1. **Password Theft** - Admin credentials sent in plain text
2. **Session Hijacking** - Session cookies can be intercepted
3. **Data Exposure** - All API requests/responses visible to attackers
4. **Compliance Issues** - May violate data protection regulations
5. **Brand Damage** - Security breaches harm reputation

### Benefits of Proper Setup:
1. **Encrypted Communication** - All data encrypted in transit
2. **Secure Cookies** - Protection against session hijacking
3. **Browser Security** - Modern security headers enabled
4. **Compliance Ready** - Meets basic security requirements
5. **Production-Like** - Test security features before production

## Monitoring and Alerts

### Set up monitoring for:
- Failed login attempts
- 500 errors (potential security issues)
- Unusual traffic patterns
- Certificate expiration

### Regular Security Tasks:
- Monthly security header audit
- Quarterly dependency updates
- Annual penetration testing
- Certificate renewal (if not auto-renewed)

## Emergency Procedures

### If Compromised:
1. Rotate all secrets immediately
2. Review access logs
3. Update all passwords
4. Notify security team
5. Document incident

### Quick Disable Commands:
```bash
# Emergency shutdown
aws ecs update-service --cluster staging-cluster --service staging-django-service --desired-count 0

# Rotate secrets
aws secretsmanager rotate-secret --secret-id staging/trazo/backend
```

## Cost Considerations

### Free/Low-Cost Security Options:
1. **Self-signed certificates** - Free but shows warnings
2. **Let's Encrypt via ACM** - Free trusted certificates
3. **CloudFront** - Free SSL termination + CDN benefits
4. **AWS WAF** - Basic rules free with CloudFront

### Estimated Additional Costs:
- ACM certificates: Free
- CloudFront: ~$1-5/month for staging traffic
- WAF rules: ~$5/month (optional)
- Total: <$10/month for proper security

## Conclusion

**Current workaround (HTTP-only) should be TEMPORARY**. Implement HTTPS within:
- 24 hours for self-signed cert
- 1 week for proper ACM certificate
- Never run staging without HTTPS long-term

Remember: **Security is not optional**, even in staging environments.