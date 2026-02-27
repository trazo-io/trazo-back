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
        header = self.get_header(request)

        if header is None:
            cookie_name = settings.SIMPLE_JWT.get("AUTH_COOKIE", "access_token")
            raw_token = request.COOKIES.get(cookie_name) or None
            if raw_token:
                enforce_csrf(request)
        else:
            raw_token = self.get_raw_token(header)

        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)

        return user, validated_token
