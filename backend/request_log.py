"""One log line per API request: who, what, result.

Added 2026-09-28. Gunicorn runs without an access log, so when a competitor's staff spent an
afternoon in the app, the only record of their API calls was what the browser analytics
happened to see; a direct API call left no trace at all. This line is what a forwarded log
search needs to answer "which user called which endpoint, from where".

Deliberately small: the path WITHOUT its query string (query strings can carry tokens and
search terms), the status, the user id (not the email), the client IP and the duration.
Only `/api/` and `/admin/` paths, so static files and health checks stay out of the log.
Sits after `JWTCookieActorMiddleware`, which is what puts the cookie user on `request.user`.
"""

import logging
import time

logger = logging.getLogger("backend.access")

_LOGGED_PREFIXES = ("/api/", "/admin/")


def client_ip(request):
    # DigitalOcean App Platform sets `do-connecting-ip` to the address that reached its edge.
    # The first X-Forwarded-For entry is whatever the client chose to send, so it comes second.
    meta = request.META
    if ip := meta.get("HTTP_DO_CONNECTING_IP"):
        return ip.strip()
    if forwarded := meta.get("HTTP_X_FORWARDED_FOR"):
        return forwarded.split(",")[0].strip()
    return meta.get("REMOTE_ADDR", "-")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(_LOGGED_PREFIXES):
            return self.get_response(request)
        started = time.monotonic()
        response = self.get_response(request)
        user = getattr(request, "user", None)
        user_id = user.pk if user is not None and user.is_authenticated else "-"
        logger.info(
            "%s %s %s user=%s ip=%s ms=%d",
            request.method,
            request.path,
            response.status_code,
            user_id,
            client_ip(request),
            (time.monotonic() - started) * 1000,
        )
        return response
