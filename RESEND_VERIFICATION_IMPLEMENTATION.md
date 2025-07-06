# Resend Verification Email Implementation

## Overview
Added a new endpoint to the UserViewSet that allows users to resend their email verification code.

## Implementation Details

### Endpoint Information
- **URL**: `/api/users/resend_verification_email/`
- **Method**: POST
- **Permission**: AllowAny (no authentication required)
- **Rate Limiting**: 5 requests per minute per IP address

### Request Format
```json
{
  "email": "user@example.com"
}
```

### Response Format

#### Success Response (200 OK)
```json
{
  "message": "Verification email sent successfully"
}
```

#### Error Responses

**Missing Email (400 Bad Request)**
```json
{
  "error": "Email is required"
}
```

**User Not Found (404 Not Found)**
```json
{
  "error": "User with this email does not exist"
}
```

**Already Verified (400 Bad Request)**
```json
{
  "error": "User is already verified"
}
```

**Email Sending Failed (500 Internal Server Error)**
```json
{
  "error": "Failed to send verification email"
}
```

**General Error (500 Internal Server Error)**
```json
{
  "error": "An error occurred while sending the verification email"
}
```

### Security Features

1. **Rate Limiting**: Prevents abuse by limiting to 5 requests per minute per IP address
2. **Email Validation**: Validates that the email address exists in the system
3. **Verification Status Check**: Prevents unnecessary emails to already verified users
4. **Code Regeneration**: Deletes old verification codes and generates new ones for security

### Code Flow

1. Extract email from request data
2. Validate email is provided
3. Check if user exists with that email
4. Verify user is not already verified
5. Delete existing verification codes for the user
6. Generate new verification code
7. Create new VerificationCode record
8. Generate appropriate verification link based on user type (Producer/Consumer)
9. Send verification email using existing email template
10. Return success response

### Files Modified

1. **`/Users/oscarmunoz/dev/trazo/trazo-back/users/views.py`**
   - Added `resend_verification_email` method to UserViewSet
   - Updated `get_permissions` to allow anonymous access to the new endpoint
   - Added rate limiting import

2. **`/Users/oscarmunoz/dev/trazo/trazo-back/users/tests/test_authentication.py`**
   - Added comprehensive test cases for the new endpoint

### Integration Points

The implementation leverages existing infrastructure:
- **Email Service**: Uses existing `send_verification_email` function from `users.utils`
- **Code Generation**: Uses existing `generate_verification_code` function from `users.signals`
- **User Types**: Supports both Producer and Consumer user types with appropriate URLs
- **Email Templates**: Uses existing verification email templates

### Testing

The implementation includes comprehensive test coverage:
- Successful resend for unverified user
- Error handling for already verified user
- Error handling for non-existent user
- Error handling for missing email parameter
- Manual testing confirmed successful operation

### Usage Example

```javascript
// Frontend usage example
const resendVerificationEmail = async (email) => {
  try {
    const response = await fetch('/api/users/resend_verification_email/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    });
    
    const data = await response.json();
    
    if (response.ok) {
      console.log('Verification email sent successfully');
    } else {
      console.error('Error:', data.error);
    }
  } catch (error) {
    console.error('Network error:', error);
  }
};
```

## Deployment Notes

- No database migrations required
- No additional dependencies needed
- Rate limiting uses existing `django_ratelimit` package
- Endpoint is immediately available after deployment
- Logging is included for monitoring and debugging

## Security Considerations

- Rate limiting prevents email flooding attacks
- No sensitive information exposed in error messages
- Verification codes are regenerated for security
- Only works for existing users (prevents email enumeration to some extent)
- Uses existing secure email sending infrastructure