"""One formatter for the "City, ST" line, shared by every surface that prints it."""


def joined_parts(obj, attrs):
    """The recorded parts of `obj` named by `attrs`, joined with ", "; None when none is set.
    A part that is empty or only punctuation (a stored placeholder "-") is left out."""
    if obj is None:
        return None
    parts = []
    for attr in attrs:
        value = str(getattr(obj, attr, "") or "").strip()
        if value and value.strip("-\u2013\u2014.,/ "):
            parts.append(value)
    return ", ".join(parts) or None


def city_state_label(obj):
    """ "City, ST" from the parts the operation actually recorded.

    Recordkeeping review F-25 (2026-10-07): the production page printed "Tangent, -" and the
    buyer page would print the same when a state is stored as a placeholder dash. A part that
    is empty or only punctuation is left out; nothing recorded gives None, never a string with
    a hole in it.
    """
    return joined_parts(obj, ("city", "state"))
