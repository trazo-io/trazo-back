from django.middleware import csrf
from django.utils import timezone

from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import BasicUserSerializer

# Conditional ratelimit import for staging compatibility
try:
    from django.conf import settings

    if getattr(settings, "RATELIMIT_ENABLE", True) and "django_ratelimit" in getattr(settings, "INSTALLED_APPS", []):
        from django_ratelimit.decorators import ratelimit
    else:
        # Create a no-op decorator when ratelimit is disabled
        def ratelimit(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

except ImportError:
    # Fallback no-op decorator if django_ratelimit is not available
    def ratelimit(*args, **kwargs):
        def decorator(func):
            return func

        return decorator


import logging

from django.conf import settings

from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from backend.subdomain_config import APP_SUBDOMAIN, CONSUMER_SUBDOMAIN
from users.constants import CONSUMER, PRODUCER, SUPERUSER
from users.models import User, WorksIn

from .serializers import LoginSerializer, MeSerializer, RegisterSerializer

logger = logging.getLogger(__name__)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = BasicUserSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["date_joined"]
    ordering = ["-date_joined"]

    def get_queryset(self):
        if self.request.user.is_superuser:
            return User.objects.all()
        # SECURITY: Non-superusers can only access their own profile
        return User.objects.filter(id=self.request.user.id)

    def get_object(self):
        # SECURITY: Always use get_queryset() to enforce access control
        queryset = self.get_queryset()
        lookup_field_value = self.kwargs[self.lookup_field]
        from django.shortcuts import get_object_or_404

        obj = get_object_or_404(queryset, id=lookup_field_value)
        self.check_object_permissions(self.request, obj)

        return obj

    def get_permissions(self):
        # Public actions declare their own permissions via @action decorator
        if self.action in [
            "verify_email",
            "resend_verification_email",
            "request_password_reset",
            "confirm_password_reset",
        ]:
            return [AllowAny()]
        return [IsAuthenticated()]

    @action(detail=False, methods=["get"])
    def me(self, request, pk=None):
        serializer = MeSerializer(request.user, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["post"], authentication_classes=[], permission_classes=[AllowAny])
    def verify_email(self, request, pk=None):
        email = request.data.get("email")
        code = request.data.get("code")

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not code:
            return Response(
                {"error": "Verification code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Return generic error to prevent email enumeration
            return Response(
                {"error": "Verification code is invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.is_verified:
            return Response(
                {"error": "User is already verified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            verification = user.verification_code.last()
            if not verification or verification.code != code:
                return Response(
                    {"error": "Verification code is invalid"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user.verification_code.all().delete()
            user.is_verified = True
            user.is_active = True
            user.save()

            # Generate JWT tokens for automatic sign-in after verification
            from rest_framework_simplejwt.tokens import RefreshToken

            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token

            # Tokens are set as httpOnly cookies — don't expose in response body
            response = Response(
                {
                    "message": "Email verified successfully",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "user_type": user.user_type,
                        "is_verified": user.is_verified,
                    },
                },
                status=status.HTTP_200_OK,
            )

            # Set secure HTTP-only cookies for automatic authentication
            cookie_options = {
                "secure": settings.SIMPLE_JWT["AUTH_COOKIE_SECURE"],
                "httponly": settings.SIMPLE_JWT["AUTH_COOKIE_HTTP_ONLY"],
                "samesite": settings.SIMPLE_JWT["AUTH_COOKIE_SAMESITE"],
            }
            cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
            if cookie_domain:
                cookie_options["domain"] = cookie_domain

            refresh_max = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
            response.set_cookie(
                key="access",
                value=str(access_token),
                max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds(),
                **cookie_options,
            )
            response.set_cookie(
                key="refresh",
                value=str(refresh),
                max_age=refresh_max,
                **cookie_options,
            )
            response.set_cookie(
                key="logged_in",
                value="true",
                max_age=refresh_max,
                **{**cookie_options, "httponly": False},
            )

            return response
        except Exception as e:
            logger.error(f"Error verifying email: {e}")
            return Response(
                {"error": "An error occurred while verifying your email"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], authentication_classes=[], permission_classes=[AllowAny])
    def resend_verification_email(self, request, pk=None):
        """
        Resend verification email to user
        """
        # Use the conditional ratelimit already defined at module level
        from urllib.parse import quote

        from .constants import CONSUMER, PRODUCER
        from .signals import generate_verification_code
        from .utils import send_verification_email

        email = request.data.get("email")

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Return generic success to prevent email enumeration
            return Response(
                {"message": "If an account exists, a verification email has been sent"},
                status=status.HTTP_200_OK,
            )

        if user.is_verified:
            return Response(
                {"message": "If an account exists, a verification email has been sent"},
                status=status.HTTP_200_OK,
            )

        try:
            # Generate new verification code
            new_code = generate_verification_code()

            # Remove old verification codes
            user.verification_code.all().delete()

            # Create new verification code
            from .models import VerificationCode

            VerificationCode.objects.create(user=user, code=new_code)

            # Generate verification link
            encoded_email = quote(user.email)
            verification_link = ""
            user_type = int(user.user_type)
            if user_type == PRODUCER:
                verification_link = f"{settings.BASE_APP_URL}auth/verifyemail?email={encoded_email}&code={new_code}"
            elif user_type == CONSUMER:
                verification_link = (
                    f"{settings.BASE_CONSUMER_URL}auth/verifyemail?email={encoded_email}&code={new_code}"
                )

            # Send verification email
            send_verification_email(user=user, verification_code=new_code, verification_link=verification_link)

            logger.info(f"Resent verification email to {user.email}")

            return Response({"message": "Verification email sent successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error resending verification email to {user.email}: {str(e)}")
            return Response(
                {"error": "An error occurred while sending verification email"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def roles(self, request, pk=None):
        return Response([{"id": role[0], "name": role[1]} for role in WorksIn.USER_ROLES])

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def change_password(self, request, pk=None):
        """
        Change user password
        """
        from django.contrib.auth.hashers import check_password

        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not old_password:
            return Response(
                {"error": "Current password is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not new_password:
            return Response(
                {"error": "New password is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        # Verify old password
        if not check_password(old_password, user.password):
            return Response(
                {"error": "Current password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate new password
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(new_password, user)
        except ValidationError as e:
            return Response(
                {"error": e.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Set new password
        user.set_password(new_password)
        user.save()

        logger.info(f"Password changed successfully for user: {user.email}")

        # Blacklist the current refresh token to invalidate existing sessions
        refresh_token = request.COOKIES.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass  # Token may already be blacklisted or invalid

        # Clear auth cookies — user must re-login with new password
        response = Response(
            {"message": "Password changed successfully. Please sign in again."},
            status=status.HTTP_200_OK,
        )
        cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
        samesite = settings.SIMPLE_JWT.get("AUTH_COOKIE_SAMESITE", "Lax")
        for cookie_name in ("access", "refresh", "logged_in"):
            response.delete_cookie(
                cookie_name,
                domain=cookie_domain,
                path="/",
                samesite=samesite,
            )
        return response

    @action(detail=False, methods=["post"], authentication_classes=[], permission_classes=[AllowAny])
    def request_password_reset(self, request, pk=None):
        """
        Request password reset via email
        Following 2025 security best practices with rate limiting
        """
        from datetime import timedelta
        from urllib.parse import quote

        from .constants import CONSUMER, PRODUCER
        from .models import PasswordResetToken
        from .utils import generate_password_reset_token, send_password_reset_email

        email = request.data.get("email")

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Always return success to prevent email enumeration attacks
        # This is a security best practice for 2025
        try:
            user = User.objects.get(email=email.lower())
        except User.DoesNotExist:
            logger.warning(f"Password reset requested for non-existent email: {email}")
            # Still return success response to prevent email enumeration
            return Response(
                {"message": "If an account with this email exists, a password reset link has been sent"},
                status=status.HTTP_200_OK,
            )

        # Check rate limiting: max 3 requests per hour per user
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_requests = PasswordResetToken.objects.filter(user=user, created_at__gte=one_hour_ago).count()

        if recent_requests >= 3:
            logger.warning(f"Rate limit exceeded for password reset: {email}")
            # Return generic success to prevent abuse detection
            return Response(
                {"message": "If an account with this email exists, a password reset link has been sent"},
                status=status.HTTP_200_OK,
            )

        # Invalidate any existing tokens for this user
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())

        # Generate new secure token
        token = generate_password_reset_token()
        expires_at = timezone.now() + timedelta(minutes=15)  # 15-minute expiration

        # Get client IP and user agent for security tracking
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        # Create password reset token
        reset_token = PasswordResetToken.objects.create(
            user=user, token=token, expires_at=expires_at, ip_address=ip_address, user_agent=user_agent
        )

        # Generate reset link based on user type
        encoded_email = quote(user.email)
        user_type = int(user.user_type)

        if user_type == PRODUCER:
            reset_link = f"{settings.BASE_APP_URL}auth/reset-password?token={token}&email={encoded_email}"
        elif user_type == CONSUMER:
            reset_link = f"{settings.BASE_CONSUMER_URL}auth/reset-password?token={token}&email={encoded_email}"
        else:
            reset_link = f"{settings.BASE_APP_URL}auth/reset-password?token={token}&email={encoded_email}"

        # Send password reset email
        try:
            email_sent = send_password_reset_email(user=user, reset_token=token, reset_link=reset_link)

            if email_sent:
                logger.info(f"Password reset email sent successfully to {user.email}")
            else:
                logger.error(f"Failed to send password reset email to {user.email}")
        except Exception as e:
            logger.error(f"Error sending password reset email to {user.email}: {str(e)}")

        # Always return success response (security best practice)
        return Response(
            {"message": "If an account with this email exists, a password reset link has been sent"},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], authentication_classes=[], permission_classes=[AllowAny])
    def confirm_password_reset(self, request, pk=None):
        """
        Confirm password reset with token and set new password
        Following 2025 security best practices
        """
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        from .models import PasswordResetToken

        token = request.data.get("token")
        email = request.data.get("email")
        new_password = request.data.get("new_password")

        # Validate required fields
        if not all([token, email, new_password]):
            return Response(
                {"error": "Token, email, and new password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Find the password reset token
            reset_token = PasswordResetToken.objects.get(token=token, user__email=email.lower())

            # Validate token
            if not reset_token.is_valid():
                if reset_token.is_expired():
                    return Response(
                        {"error": "Password reset token has expired. Please request a new one."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                elif reset_token.is_used():
                    return Response(
                        {"error": "Password reset token has already been used. Please request a new one."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                else:
                    return Response(
                        {"error": "Invalid password reset token"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            user = reset_token.user

            # Validate new password
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return Response(
                    {"error": e.messages},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Set new password.
            #
            # ⛔ `is_active` / `is_verified` are set HERE too, and that is not incidental.
            # `verify_email` used to be the only thing that flipped them, so an account that
            # signed up and never clicked the link was stuck: `authenticate()` rejects
            # `is_active=False`, signup answered "an account already exists, sign in instead",
            # sign-in answered "No active account found with the given credentials", and this
            # endpoint answered "You can now sign in with your new password" — which was
            # FALSE. Three screens, each pointing at the next, none of them a way out.
            #
            # Activating here is not a weakening. The reset token was delivered to the address
            # on the account and is single-use and 15-minute-lived; holding it proves control
            # of that mailbox, which is the entire thing the signup code proves. Anyone who
            # can complete this flow could equally have completed `verify_email`.
            #
            # Pending verification codes are deliberately NOT deleted: `verify_email` answers
            # an already-verified user with "User is already verified", which is true and
            # legible, whereas deleting the row would answer the same click with
            # "Verification code is invalid", which is neither.
            user.set_password(new_password)
            user.is_verified = True
            user.is_active = True
            user.save(update_fields=["password", "is_verified", "is_active"])

            # Mark token as used
            reset_token.mark_as_used()

            # Invalidate all other tokens for this user
            PasswordResetToken.objects.filter(user=user, used_at__isnull=True).exclude(id=reset_token.id).update(
                used_at=timezone.now()
            )

            logger.info(f"Password reset completed successfully for user: {user.email}")

            return Response(
                {"message": "Password reset successfully. You can now sign in with your new password."},
                status=status.HTTP_200_OK,
            )

        except PasswordResetToken.DoesNotExist:
            return Response(
                {"error": "Invalid or expired password reset token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error during password reset confirmation: {str(e)}")
            return Response(
                {"error": "An error occurred while resetting your password. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LoginViewSet(viewsets.ModelViewSet, TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]  # Explicitly allow anonymous access
    authentication_classes = []  # No authentication required for login
    http_method_names = ["post"]

    def get_subdomain(self, request):
        # First try to get from Origin header
        origin = request.headers.get("Origin")
        if origin:
            # Parse the origin URL
            from urllib.parse import urlparse

            parsed_uri = urlparse(origin)
            # Get the hostname (e.g., 'app.localhost:3000' or 'app.trazo.io')
            hostname = parsed_uri.netloc
            # Split and get first part
            subdomain = hostname.split(".")[0]
            return subdomain

        # Fallback to host header
        host = request.get_host()
        return host.split(".")[0] if "." in host else None

    def create(self, request, *args, **kwargs):
        # Enforce CSRF — DRF skips CsrfViewMiddleware when authentication_classes is empty
        from .auth import enforce_csrf

        enforce_csrf(request)

        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        # Get user type and validate subdomain access
        user_type = serializer.validated_data.get("user_type")
        subdomain = self.get_subdomain(request)

        if subdomain == APP_SUBDOMAIN:
            if user_type not in [SUPERUSER, PRODUCER]:
                return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)
        elif subdomain == CONSUMER_SUBDOMAIN:
            if user_type == CONSUMER:
                # Add additional consumer-specific validation if needed
                pass
        else:
            return Response({"error": "Invalid domain"}, status=status.HTTP_403_FORBIDDEN)

        remember_me = request.data.get("remember_me", False)

        # Strip tokens from response body — they are set as httpOnly cookies only
        response_data = {k: v for k, v in serializer.validated_data.items() if k not in ("access", "refresh")}
        response = Response(response_data, status=status.HTTP_200_OK)

        # Set secure cookie options
        cookie_options = {
            "secure": settings.SIMPLE_JWT["AUTH_COOKIE_SECURE"],
            "httponly": settings.SIMPLE_JWT["AUTH_COOKIE_HTTP_ONLY"],
            "samesite": settings.SIMPLE_JWT["AUTH_COOKIE_SAMESITE"],
        }

        cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
        if cookie_domain:
            cookie_options["domain"] = cookie_domain

        # Remember Me: persistent cookie (30 days) vs session cookie (cleared on browser close)
        if remember_me:
            refresh_lifetime = settings.SIMPLE_JWT["REMEMBER_ME_REFRESH_TOKEN_LIFETIME"]
        else:
            refresh_lifetime = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]

        # Access token: always short-lived persistent cookie (15 min)
        response.set_cookie(
            key="access",
            value=serializer.validated_data["access"],
            max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds(),
            **cookie_options,
        )

        # Refresh token: persistent if remember_me, session cookie otherwise
        refresh_cookie_opts = {**cookie_options}
        if remember_me:
            refresh_cookie_opts["max_age"] = int(refresh_lifetime.total_seconds())
        # When remember_me is False, omitting max_age creates a session cookie
        # that is deleted when the browser closes — this is the standard behavior

        response.set_cookie(
            key="refresh",
            value=serializer.validated_data["refresh"],
            **refresh_cookie_opts,
        )

        # Non-httpOnly flag so frontend can detect login status
        logged_in_opts = {**cookie_options, "httponly": False}
        if remember_me:
            logged_in_opts["max_age"] = int(refresh_lifetime.total_seconds())
        response.set_cookie(key="logged_in", value="true", **logged_in_opts)

        csrf.get_token(request)
        return response


class RegistrationViewSet(viewsets.ModelViewSet, TokenObtainPairView):
    serializer_class = RegisterSerializer
    permission_classes = (AllowAny,)
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        # Enforce CSRF — DRF skips CsrfViewMiddleware when authentication_classes is empty
        from .auth import enforce_csrf

        enforce_csrf(request)

        serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # Tokens are set as httpOnly cookies — don't expose in response body
        response = Response(
            {"user": serializer.data},
            status=status.HTTP_201_CREATED,
        )

        # Set httpOnly auth cookies (default session-only for new registrations)
        cookie_options = {
            "secure": settings.SIMPLE_JWT["AUTH_COOKIE_SECURE"],
            "httponly": settings.SIMPLE_JWT["AUTH_COOKIE_HTTP_ONLY"],
            "samesite": settings.SIMPLE_JWT["AUTH_COOKIE_SAMESITE"],
        }
        cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
        if cookie_domain:
            cookie_options["domain"] = cookie_domain

        response.set_cookie(
            key="access",
            value=access_token,
            max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds(),
            **cookie_options,
        )
        refresh_max = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
        response.set_cookie(
            key="refresh",
            value=refresh_token,
            max_age=refresh_max,
            **cookie_options,
        )
        response.set_cookie(
            key="logged_in",
            value="true",
            max_age=refresh_max,
            **{**cookie_options, "httponly": False},
        )
        csrf.get_token(request)

        return response


class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _get_cookie_options(self):
        opts = {
            "secure": settings.SIMPLE_JWT["AUTH_COOKIE_SECURE"],
            "httponly": settings.SIMPLE_JWT["AUTH_COOKIE_HTTP_ONLY"],
            "samesite": settings.SIMPLE_JWT["AUTH_COOKIE_SAMESITE"],
        }
        cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
        if cookie_domain:
            opts["domain"] = cookie_domain
        return opts

    def _set_auth_cookies(self, response, access_token, refresh_token, request):
        cookie_options = self._get_cookie_options()

        # Preserve remember_me preference: if existing refresh cookie had max_age,
        # the browser kept it across sessions. We mirror that by checking the
        # logged_in cookie (only set with max_age when remember_me was True).
        has_persistent_session = request.COOKIES.get("logged_in") is not None

        response.set_cookie(
            key="access",
            value=access_token,
            max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds(),
            **cookie_options,
        )

        refresh_opts = {**cookie_options}
        logged_in_opts = {**cookie_options, "httponly": False}

        if has_persistent_session:
            refresh_max = int(settings.SIMPLE_JWT["REMEMBER_ME_REFRESH_TOKEN_LIFETIME"].total_seconds())
            refresh_opts["max_age"] = refresh_max
            logged_in_opts["max_age"] = refresh_max

        response.set_cookie(key="refresh", value=refresh_token, **refresh_opts)
        response.set_cookie(key="logged_in", value="true", **logged_in_opts)
        csrf.get_token(request)

    def post(self, request, *args, **kwargs):
        """
        Cookie-based refresh with body fallback.
        Reads refresh token from httpOnly cookie first, falls back to request body.
        """
        # Enforce CSRF since DRF exempts APIView from Django's CsrfViewMiddleware
        from .auth import enforce_csrf

        enforce_csrf(request)

        # Prefer cookie-based refresh (httpOnly cookie set by login)
        refresh_from_cookie = request.COOKIES.get("refresh")
        if refresh_from_cookie:
            data = {"refresh": refresh_from_cookie}
        else:
            data = request.data

        serializer = self.get_serializer(data=data)
        try:
            if not serializer.is_valid():
                return Response({"error": "Token is invalid or expired"}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        access_token = serializer.validated_data["access"]
        refresh_token = serializer.validated_data["refresh"]

        # Strip tokens from response body — they are set as httpOnly cookies only
        response_data = {k: v for k, v in serializer.validated_data.items() if k not in ("access", "refresh")}
        response = Response(response_data, status=status.HTTP_200_OK)
        self._set_auth_cookies(response, access_token, refresh_token, request)
        return response


class APILogoutView(APIView):
    """
    SECURITY: Logout endpoint with CSRF protection enabled
    State-changing operations should always be protected against CSRF attacks
    """

    permission_classes = (IsAuthenticated,)
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        # Blacklist the refresh token to prevent reuse
        refresh_token = request.COOKIES.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass  # Token may already be blacklisted or invalid

        response = Response({"data": {"user": "ok"}}, status=status.HTTP_200_OK)

        cookie_domain = settings.SIMPLE_JWT.get("AUTH_COOKIE_DOMAIN")
        samesite = settings.SIMPLE_JWT.get("AUTH_COOKIE_SAMESITE", "Lax")

        for cookie_name in ("access", "refresh", "logged_in"):
            response.delete_cookie(
                cookie_name,
                domain=cookie_domain,
                path="/",
                samesite=samesite,
            )

        return response
