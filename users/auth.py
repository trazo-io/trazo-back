# cookieapp/authenticate.py
import logging

from django.conf import settings

from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger(__name__)


def enforce_csrf(request):
    def dummy_get_response(request):  # pragma: no cover
        return None

    check = CSRFCheck(dummy_get_response)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})

    if reason:
        raise exceptions.PermissionDenied("CSRF Failed: %s" % reason)


class CustomAuthentication(JWTAuthentication):
    def authenticate(self, request):
        try:
            logger.info(f"🔐 CustomAuthentication: STARTING {request.method} {request.path}")

            header = self.get_header(request)
            logger.info(f"🔐 CustomAuthentication: Authorization header: {bool(header)}")

            if header is None:
                cookie_name = settings.SIMPLE_JWT.get("AUTH_COOKIE", "access_token")
                raw_token = request.COOKIES.get(cookie_name) or None
                logger.info(f"🔐 CustomAuthentication: Cookie '{cookie_name}': {'Found' if raw_token else 'Not found'}")
                if not raw_token:
                    logger.info(f"🔐 CustomAuthentication: All cookies: {list(request.COOKIES.keys())}")
            else:
                raw_token = self.get_raw_token(header)
                logger.info(f"🔐 CustomAuthentication: Raw token from header: {'Found' if raw_token else 'Not found'}")

            if raw_token is None:
                logger.info("🔐 CustomAuthentication: No token found - returning None")
                return None

            logger.info(f"🔐 CustomAuthentication: Token length: {len(raw_token)}")

            try:
                validated_token = self.get_validated_token(raw_token)
                logger.info("🔐 CustomAuthentication: ✅ Token validated successfully")
            except Exception as e:
                logger.error(f"🔐 CustomAuthentication: ❌ Token validation failed: {type(e).__name__}: {e}")
                raise

            user = self.get_user(validated_token)
            logger.info(f"🔐 CustomAuthentication: ✅ User found: {user.email if user else 'None'}")

            return user, validated_token

        except Exception as e:
            logger.error(f"🔐 CustomAuthentication: 💥 EXCEPTION: {type(e).__name__}: {e}")
            import traceback

            logger.error(f"🔐 CustomAuthentication: 💥 TRACEBACK: {traceback.format_exc()}")
            raise
