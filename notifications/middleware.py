import logging
from urllib.parse import parse_qs

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

import jwt
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware

logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_jwt(token):
    """Get user from JWT token"""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser

    User = get_user_model()

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")

        if user_id:
            user = User.objects.get(id=user_id)
            return user
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, User.DoesNotExist) as e:
        logger.warning(f"JWT authentication failed: {e}")

    return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Middleware to authenticate WebSocket connections using JWT token
    """

    async def __call__(self, scope, receive, send):
        # Close old database connections to prevent usage of timed out connections
        close_old_connections()

        # Get the token from query parameters
        query_string = scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)
        token = query_params.get("token", [None])[0]

        # If no token in query params, try to get from headers (for future compatibility)
        if not token:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        # If no token in headers, try cookies (session-based auth)
        if not token:
            # Check for session-based authentication
            session_key = None
            cookies = headers.get(b"cookie", b"").decode()
            if cookies:
                for cookie in cookies.split(";"):
                    if "sessionid=" in cookie:
                        session_key = cookie.split("sessionid=")[1].strip()
                        break

            if session_key:
                # Let Django's session auth handle this
                scope["user"] = await self.get_user_from_session(session_key)
            else:
                from django.contrib.auth.models import AnonymousUser

                scope["user"] = AnonymousUser()
        else:
            # Authenticate using JWT
            scope["user"] = await get_user_from_jwt(token)

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def get_user_from_session(self, session_key):
        """Get user from Django session"""
        try:
            from django.contrib.auth import get_user
            from django.contrib.sessions.models import Session
            from django.http import HttpRequest

            session = Session.objects.get(session_key=session_key)
            if session.expire_date > timezone.now():
                # Create a fake request to use Django's auth system
                request = HttpRequest()
                request.session = session.get_decoded()
                user = get_user(request)
                from django.contrib.auth.models import AnonymousUser

                return user if user.is_authenticated else AnonymousUser()
        except (Session.DoesNotExist, Exception) as e:
            logger.warning(f"Session authentication failed: {e}")

        from django.contrib.auth.models import AnonymousUser

        return AnonymousUser()


def JWTAuthMiddlewareStack(inner):
    """
    WebSocket authentication middleware stack with JWT support
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
