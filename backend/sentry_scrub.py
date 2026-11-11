"""What the server sends to Sentry, and what it must not (OV-SEC-C17, 2026-11-11).

`send_default_pii=False` already keeps the user's IP address, cookies and auth headers out, and the
default event scrubber masks keys such as `password` and `token`. Two things still went out:

  * the request URL with its query string, and with the credential that some routes carry IN
    THE PATH: `/api/certifier-review/<token>/...`, `/api/buyer-review/<token>/` (each a read of
    one grower's records) and `/api/invitation/<invitation_code>/...`;
  * the request BODY. The scrubber matches key names, and `verify_email` posts `email` and `code`,
    neither of which is on its list.

So bodies are never sent (`max_request_body_size="never"`, set in prod.py) and every URL loses its
query string and has those path segments masked, the same segments `backend/request_log.py` masks
in the access log. The browser does the same in `trazo-app/src/config/sentryScrub.ts`.
"""

import re

_PATH_CREDENTIAL = re.compile(r"(/(?:certifier-review|buyer-review|invitation)/)[^/?#]+")


def scrub_url(url):
    if not isinstance(url, str):
        return url
    cut = re.search(r"[?#]", url)
    if cut:
        url = url[: cut.start()]
    return _PATH_CREDENTIAL.sub(r"\1[redacted]", url)


def scrub_event(event, hint=None):
    request = event.get("request")
    if isinstance(request, dict):
        if "url" in request:
            request["url"] = scrub_url(request["url"])
        for key in ("query_string", "data", "cookies"):
            request.pop(key, None)
    breadcrumbs = event.get("breadcrumbs")
    crumbs = breadcrumbs.get("values", []) if isinstance(breadcrumbs, dict) else breadcrumbs or []
    for crumb in crumbs:
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if isinstance(data, dict) and "url" in data:
            data["url"] = scrub_url(data["url"])
    return event
