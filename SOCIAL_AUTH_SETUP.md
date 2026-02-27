# Social Authentication Setup Guide for Trazo

This guide explains how to configure Google, Facebook, and Apple Sign In for both producer and consumer platforms in Trazo.

## Overview

Trazo supports social authentication for:
- **Producer Platform** (`app.localhost:3000`) - Agricultural businesses and farms
- **Consumer Platform** (`consumer.localhost:3000`) - End consumers scanning QR codes

## Architecture

### Backend
- **Framework**: Django with django-allauth
- **Endpoint**: `/auth/social/`
- **Authentication**: JWT tokens with custom user types
- **User Types**: 
  - `4` = Producer (agricultural business)
  - `5` = Consumer (end-user)

### Frontend
- **Provider**: React with custom OAuth utilities
- **State Management**: Redux Toolkit + RTK Query
- **UI Components**: Chakra UI with modern design patterns

## Setup Instructions

### 1. Google OAuth 2.0 Setup

#### Google Cloud Console Configuration

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Create a new project or select existing one

2. **Enable Required APIs**
   ```bash
   - Google Identity Toolkit API
   - Google+ API (deprecated but still needed for some legacy auth flows)
   ```

3. **Create OAuth 2.0 Credentials**
   - Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client IDs"
   - Application type: Web application
   - Name: "Trazo Social Auth"

4. **Configure Authorized Domains**
   ```
   localhost
   app.localhost
   consumer.localhost
   ```

5. **Configure Authorized Redirect URIs**
   ```
   http://localhost:3000
   http://app.localhost:3000
   http://consumer.localhost:3000
   ```

6. **Get Credentials**
   - Client ID: `your_client_id.apps.googleusercontent.com`
   - Client Secret: `your_client_secret`

#### Environment Configuration

**Backend (.env)**
```bash
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret
```

**Frontend (.env)**
```bash
VITE_GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
```

### 2. Facebook OAuth 2.0 Setup

#### Facebook Developers Configuration

1. **Go to Facebook Developers**
   - Visit: https://developers.facebook.com/
   - Click "My Apps" → "Create App"
   - Select **Consumer** or **Business** type
   - App name: e.g. `Trazo Dev`

2. **Configure Facebook Login**
   - Go to **Casos de uso** (Use Cases) → find "Facebook Login" → **Personalizar** (Customize)
   - Go to the **Configurar** (Settings) tab
   - Add **Valid OAuth Redirect URIs**: `https://localhost:3000/` (must be HTTPS, see note below)

3. **Configure App Settings**
   - Go to **Configuracion de la app** → **Basica**
   - **Do NOT add `localhost` to App Domains** - Facebook rejects it (requires TLD like `.com`)
   - Leave App Domains empty for local development
   - Copy the **App ID** (Identificador de la app) and **App Secret** (Clave secreta)

4. **Get Credentials**
   - App ID: Found in App Settings → Basic (top of the page)
   - App Secret: Found in App Settings → Basic (click "Show")

> **IMPORTANT: Facebook enforces HTTPS even in development mode.**
> The "Aplicar HTTPS" (Enforce HTTPS) toggle in Facebook Login settings cannot be
> disabled (as of 2026). This means Facebook Login **cannot be tested on plain
> `http://localhost:3000`**. Options:
> - **Skip local testing** - the code works identically to Google auth (verified).
>   Test on staging where HTTPS is available.
> - **Enable HTTPS on Vite** - install `@vitejs/plugin-basic-ssl` to serve localhost
>   over HTTPS. Requires reconfiguring Google OAuth redirect URIs too.
>
> Facebook Login will work correctly on staging (`https://app-staging.trazo.io`) and
> production (`https://app.trazo.io`) without any workarounds.

#### Environment Configuration

**Backend (.env)**
```bash
FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret
```

**Frontend (.env.local)**
```bash
VITE_FACEBOOK_APP_ID=your_facebook_app_id
```

### 3. Apple Sign In Setup (Deferred)

> **NOTE**: Apple Sign In for web requires a paid Apple Developer Program membership
> ($99/year). This is currently **deferred** - Apple buttons have been removed from
> all auth pages. The backend handler (`social_auth.py:handle_apple_auth`) remains
> in place and can be re-enabled when an Apple Developer account is available.

#### When ready to enable:

1. **Create App ID**
   - Go to: https://developer.apple.com/account/resources/identifiers/
   - Create new App ID with "Sign In with Apple" capability

2. **Create Service ID**
   - Create new Service ID for web authentication
   - Configure return URLs:
     ```
     https://app.trazo.io/auth/apple/callback
     https://consumer.trazo.io/auth/apple/callback
     ```

3. **Create Private Key**
   - Create new key with "Sign In with Apple" capability
   - Download the .p8 file (only downloadable once)

4. **Get Required Information**
   - Client ID: Your Service ID
   - Team ID: Found in membership details
   - Key ID: From the private key you created
   - Private Key: Content of the .p8 file

5. **Re-add Apple buttons** to frontend auth pages (removed in commit that deferred Apple)

#### Environment Configuration

**Backend (.env)**
```bash
APPLE_CLIENT_ID=your.apple.service.id
APPLE_CLIENT_SECRET=your_generated_jwt_token
APPLE_TEAM_ID=your_team_id
APPLE_KEY_ID=your_key_id
APPLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----
your_private_key_content
-----END PRIVATE KEY-----
```

**Frontend (.env.local)**
```bash
VITE_APPLE_CLIENT_ID=your.apple.service.id
```

## Implementation Details

### Backend Implementation

The backend uses a unified social authentication endpoint at `/auth/social/` that handles all three providers:

```python
# POST /auth/social/
{
    "provider": "google|facebook|apple",
    "access_token": "provider_access_token",  # For Google & Facebook
    "id_token": "provider_id_token",          # For Google & Apple
    "user_type": 4,                           # 4=Producer, 5=Consumer
    "user": {                                 # For Apple (name data)
        "name": {
            "firstName": "John",
            "lastName": "Doe"
        }
    }
}
```

**Response:**
```json
{
    "user": {
        "id": 123,
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "user_type": 4,
        "social_auth_provider": "google"
    },
    "access": "jwt_access_token",
    "refresh": "jwt_refresh_token",
    "user_type": 4
}
```

### Frontend Implementation

The frontend uses OAuth libraries and redirects users based on their type:

**Producer Flow:**
1. User clicks social login on `app.localhost:3000/auth/signin`
2. OAuth popup/redirect authenticates with provider
3. Frontend calls `/auth/social/` with `user_type: 4`
4. Success → Redirect to `/admin/dashboard`

**Consumer Flow:**
1. User clicks social login on `consumer.localhost:3000/auth/signin`
2. OAuth popup/redirect authenticates with provider
3. Frontend calls `/auth/social/` with `user_type: 5`
4. Success → Redirect to `/admin/dashboard/scans`

## Security Considerations

### CORS Configuration
```python
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://app.localhost:3000",
    "http://consumer.localhost:3000"
]
```

### JWT Security
- Access tokens expire in 20 minutes
- Refresh tokens expire in 24 hours
- Tokens are stored in HTTP-only cookies
- CSRF protection enabled

### Provider Security
- **Google**: Verifies ID tokens using Google's public keys
- **Facebook**: Validates access tokens with Facebook Graph API
- **Apple**: Verifies ID tokens using Apple's public keys

## Testing

### Local Development Testing

1. **Start Backend**
   ```bash
   cd trazo-back
   poetry run python manage.py runserver
   ```

2. **Start Frontend**
   ```bash
   cd trazo-app
   npm start
   ```

3. **Test URLs**
   - Producer: http://app.localhost:3000/auth/signin
   - Consumer: http://consumer.localhost:3000/auth/signin

### Test Social Authentication

1. Click on Google/Facebook/Apple buttons
2. Complete OAuth flow in popup/redirect
3. Verify user creation in Django admin
4. Check JWT token in browser cookies
5. Verify redirect to correct dashboard

## Troubleshooting

### Common Issues

1. **"OAuth Client ID not configured"**
   - Check environment variables are set correctly
   - Verify client IDs match OAuth provider configuration

2. **"Invalid redirect URI"**
   - Ensure redirect URIs are exactly configured in OAuth provider
   - Check for http vs https mismatches

3. **"CORS errors"**
   - Verify CORS_ALLOWED_ORIGINS includes your frontend URL
   - Check that frontend is running on expected port

4. **"Token verification failed"**
   - For Google: Check client ID matches the ID token audience
   - For Apple: Verify private key and team ID are correct
   - For Facebook: Ensure access token is valid and not expired

### Debug Mode

Enable debug logging in Django settings:
```python
LOGGING = {
    'loggers': {
        'users.social_auth': {
            'level': 'DEBUG',
            'handlers': ['console'],
        }
    }
}
```

## Production Deployment Checklist

Create **separate** OAuth apps/projects for each environment (dev, staging, production). Never reuse dev credentials in production.

### Trazo Domain Reference

| Environment | Backend API | Producer Frontend | Consumer Frontend |
|-------------|-------------|-------------------|-------------------|
| **Development** | `http://localhost:8000` | `http://app.localhost:3000` | `http://consumer.localhost:3000` |
| **Staging** | `https://api-staging.trazo.io` | `https://app-staging.trazo.io` | `https://consumer-staging.trazo.io` |
| **Production** | `https://api.trazo.io` | `https://app.trazo.io` | `https://consumer.trazo.io` |

---

### 1. Google Cloud Project (per environment)

**Console**: https://console.cloud.google.com/

- [ ] Create project (e.g. `trazo-prod`, `trazo-staging`)
- [ ] Enable **Google Identity Toolkit API**
- [ ] Go to **Credentials** > **Create OAuth 2.0 Client ID** (Web application)
- [ ] Set **Authorized JavaScript origins**:
  ```
  # Staging
  https://app-staging.trazo.io
  https://consumer-staging.trazo.io

  # Production
  https://app.trazo.io
  https://consumer.trazo.io
  ```
- [ ] Set **Authorized redirect URIs**:
  ```
  # Staging
  https://app-staging.trazo.io/auth/google/callback
  https://consumer-staging.trazo.io/auth/google/callback

  # Production
  https://app.trazo.io/auth/google/callback
  https://consumer.trazo.io/auth/google/callback
  ```
- [ ] Configure **OAuth consent screen** (External, publish to production)
- [ ] Copy **Client ID** and **Client Secret**
- [ ] Set env vars:
  ```bash
  # Backend (ECS task definition / Secrets Manager)
  GOOGLE_CLIENT_ID=<client_id>.apps.googleusercontent.com
  GOOGLE_CLIENT_SECRET=<client_secret>

  # Frontend (Netlify env vars)
  VITE_GOOGLE_CLIENT_ID=<client_id>.apps.googleusercontent.com
  ```

---

### 2. Facebook Developer App (per environment)

**Console**: https://developers.facebook.com/

- [ ] Create app (Business type) > e.g. `Trazo Production`
- [ ] Add **Facebook Login** product
- [ ] Go to **Facebook Login** > **Settings**
- [ ] Set **Valid OAuth Redirect URIs**:
  ```
  # Staging
  https://app-staging.trazo.io/
  https://consumer-staging.trazo.io/

  # Production
  https://app.trazo.io/
  https://consumer.trazo.io/
  ```
- [ ] Go to **App Settings** > **Basic**
- [ ] Set **App Domains**:
  ```
  # Staging
  app-staging.trazo.io
  consumer-staging.trazo.io

  # Production
  app.trazo.io
  consumer.trazo.io
  ```
- [ ] Set **Privacy Policy URL**: `https://trazo.io/privacy`
- [ ] Set **Terms of Service URL**: `https://trazo.io/terms`
- [ ] Switch app to **Live** mode (requires privacy policy + app review)
- [ ] Copy **App ID** and **App Secret**
- [ ] Set env vars:
  ```bash
  # Backend
  FACEBOOK_APP_ID=<app_id>
  FACEBOOK_APP_SECRET=<app_secret>

  # Frontend
  VITE_FACEBOOK_APP_ID=<app_id>
  ```

---

### 3. Apple Developer (per environment)

**Console**: https://developer.apple.com/account/

- [ ] Go to **Identifiers** > Create **App ID**
  - Enable **Sign In with Apple** capability
- [ ] Go to **Identifiers** > Create **Services ID**
  - Identifier: e.g. `io.trazo.auth` (production) / `io.trazo.auth.staging` (staging)
  - Enable **Sign In with Apple**
  - Configure **Web Authentication**:
    - **Domains**:
      ```
      # Staging
      app-staging.trazo.io
      consumer-staging.trazo.io

      # Production
      app.trazo.io
      consumer.trazo.io
      ```
    - **Return URLs**:
      ```
      # Staging
      https://app-staging.trazo.io/auth/apple/callback
      https://consumer-staging.trazo.io/auth/apple/callback

      # Production
      https://app.trazo.io/auth/apple/callback
      https://consumer.trazo.io/auth/apple/callback
      ```
- [ ] Go to **Keys** > Create key with **Sign In with Apple** enabled
- [ ] Download the `.p8` private key file (only downloadable once)
- [ ] Note your **Team ID** (from Membership page) and **Key ID**
- [ ] Set env vars:
  ```bash
  # Backend
  APPLE_CLIENT_ID=io.trazo.auth  # Your Services ID
  APPLE_TEAM_ID=<team_id>
  APPLE_KEY_ID=<key_id>
  APPLE_PRIVATE_KEY=<contents of .p8 file>

  # Frontend
  VITE_APPLE_CLIENT_ID=io.trazo.auth
  ```

---

### 4. Infrastructure Env Vars Summary

Where to set the variables for each environment:

| Variable | Backend (ECS/Secrets Manager) | Frontend (Netlify) |
|----------|-------------------------------|-------------------|
| `GOOGLE_CLIENT_ID` | Yes | Yes (`VITE_GOOGLE_CLIENT_ID`) |
| `GOOGLE_CLIENT_SECRET` | Yes | No |
| `FACEBOOK_APP_ID` | Yes | Yes (`VITE_FACEBOOK_APP_ID`) |
| `FACEBOOK_APP_SECRET` | Yes | No |
| `APPLE_CLIENT_ID` | Yes | Yes (`VITE_APPLE_CLIENT_ID`) |
| `APPLE_TEAM_ID` | Yes | No |
| `APPLE_KEY_ID` | Yes | No |
| `APPLE_PRIVATE_KEY` | Yes | No |

---

### 5. Pre-Launch Verification

- [ ] All three providers tested on staging with real accounts
- [ ] Invitation + social auth flow works (user gets company assigned)
- [ ] OAuth consent screens approved/published (Google, Facebook)
- [ ] Facebook app in **Live** mode (not Development)
- [ ] Apple Services ID domains verified
- [ ] Frontend env vars set in Netlify for both `app.*` and `consumer.*` sites
- [ ] Backend env vars set in AWS Secrets Manager / ECS task definition
- [ ] CORS origins include all frontend domains (`prod.py` already configured)
- [ ] Rate limiting enabled on `/auth/social/` endpoint

## Production Considerations

### Security Headers
```python
# Already configured in prod.py
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### Rate Limiting
The social auth endpoint includes rate limiting to prevent abuse:
```python
# 5 requests per minute for social auth
RATELIMIT_ENABLE = True
```

## Support

For issues with social authentication:
1. Check Django logs for backend errors
2. Check browser console for frontend errors
3. Verify OAuth provider configuration
4. Test with different providers to isolate issues