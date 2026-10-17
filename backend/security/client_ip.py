"""The one place that decides which address a request came from.

Every rate limit, block list and audit line keys on this, so it must not be something the
client can choose.

MEASURED 2026-10-17 against production (one unauthenticated GET to /api/users/me/ sending
`DO-Connecting-IP: 203.0.113.7` and `X-Forwarded-For: 198.51.100.9`):
  - `do-connecting-ip` arrived as the real address. DigitalOcean's edge OVERWRITES it.
  - the first X-Forwarded-For entry arrived as 198.51.100.9. The edge passes the client's value
    through, so `XFF[0]` is attacker-chosen.
  - REMOTE_ADDR is a DigitalOcean ingress address (100.127.x.x), shared by every client.

Fourteen copies of "take the first X-Forwarded-For entry" used to live across the codebase, so
every IP-keyed limiter could be reset by sending a new header on each request.
NEVER: do not read HTTP_X_FORWARDED_FOR anywhere else. Guard:
`backend/security/tests/test_client_ip.py`.

Off DigitalOcean (local dev, CI) the header is absent and REMOTE_ADDR is the real peer.
"""

import ipaddress


def client_ip(request):
    meta = request.META
    if ip := meta.get("HTTP_DO_CONNECTING_IP"):
        return ip.strip()
    return meta.get("REMOTE_ADDR") or "-"


def throttle_ident(request):
    """The address a rate limit counts against.

    An IPv6 host is usually handed a whole /64, so keying on the full address gives one client
    2^64 fresh buckets. IPv4 stays per address.
    """
    ip = client_ip(request)
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6 and address.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return ip
