"""One spelling of a phone number, so a roster lookup can be an equality test.

Providers disagree about the shape. Twilio sends `whatsapp:+14155551234`, Meta sends
`14155551234` with no plus, humans type `(415) 555-1234` into the roster form. Storing whatever
arrived would mean the webhook could not find a number the supervisor had already registered, which
fails in the most confusing possible direction: the crew member is told they are not registered
while their number is visibly on the list.

This is deliberately NOT a phone-number parser. It does not know area codes, it does not validate
that a number could exist, and it does not guess a country. `phonenumbers` would do all three and is
not a dependency here. What it does is reduce a string to digits with one leading plus, which is
enough for equality, and refuse anything that cannot be reduced to a plausible length.
"""

import re

E164_RE = re.compile(r"^\+[1-9]\d{6,18}$")

_STRIP = re.compile(r"[^\d+]")


def normalise_phone(raw, *, default_country_code=None):
    """`whatsapp:+1 (415) 555-1234` -> `+14155551234`. Returns None when it cannot be trusted.

    None means "do not guess": the caller must refuse the message rather than route it somewhere.
    A number with no country code is only completed when the caller supplies `default_country_code`,
    because assuming +1 for a bare 10-digit string would silently route a Mexican crew's number to a
    US one.
    """
    if not raw:
        return None
    text = _STRIP.sub("", str(raw).strip())
    if not text:
        return None
    # A plus anywhere but the front is noise from a copy-paste, not an intention.
    text = "+" + text.replace("+", "") if text.startswith("+") else text.replace("+", "")
    if not text.startswith("+"):
        if not default_country_code:
            return None
        text = "+" + str(default_country_code).lstrip("+") + text
    return text if E164_RE.match(text) else None
