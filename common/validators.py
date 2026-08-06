"""Shared field validators for contact and postal data.

These guard values that leave the platform on documents a grower is judged by —
`contact_phone` and `zip_code` reach the Organic System Plan and the certifier
audit packet. Before this module both layers accepted anything short enough to
fit the column, so "call me maybe" was a valid business phone (2026-07-31 QA).

Phone validation deliberately normalizes to digits rather than matching a
punctuation pattern: growers, seed fixtures and imports all write US numbers
differently ("(559) 555-0142", "+1-559-555-0987", "559.555.0142"), and a strict
format regex rejects real numbers. What actually matters is that the value
contains a plausible US phone number.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from common.us_states import normalize_state

# 5-digit ZIP, optionally with the +4 add-on ("93265", "93265-1234").
US_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

_DIGITS_RE = re.compile(r"\D")


def normalize_us_phone_digits(value):
    """Return only the digits in `value`, dropping a leading US country code.

    "+1 (559) 555-0142" -> "5595550142"
    """
    digits = _DIGITS_RE.sub("", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def validate_us_phone(value):
    """Accept any formatting of a 10-digit US phone number.

    Blank/None passes — these fields are optional at the model level and this
    validator must not turn an optional field into a required one.
    """
    if value in (None, ""):
        return

    digits = normalize_us_phone_digits(value)

    if len(digits) != 10:
        raise ValidationError(
            _("Enter a 10-digit US phone number, for example (559) 555-0142."),
            code="invalid_us_phone",
        )

    # NANP: area code and exchange code both start 2-9. Rejects placeholder
    # junk like "000-000-0000" and "111-111-1111" that is digit-shaped but
    # cannot be dialed.
    if digits[0] in "01" or digits[3] in "01":
        raise ValidationError(
            _("Enter a valid US phone number, for example (559) 555-0142."),
            code="invalid_us_phone",
        )


def validate_us_zip(value):
    """Accept a 5-digit US ZIP, optionally ZIP+4. Blank/None passes."""
    if value in (None, ""):
        return

    if not US_ZIP_RE.match(value.strip()):
        raise ValidationError(
            _("Enter a 5-digit ZIP code, for example 93265."),
            code="invalid_us_zip",
        )


def validate_us_state(value):
    """Accept a US state code or full name. Blank/None passes.

    A state that does not resolve is rejected rather than stored, because every
    regional lookup downstream keys on the 2-letter code — an unresolvable value
    silently costs the farm with national defaults while the UI still shows a
    state. See common.us_states for the resolution rules.
    """
    if value in (None, ""):
        return

    if normalize_state(value) is None:
        raise ValidationError(
            _("Enter a US state, for example CA or California."),
            code="invalid_us_state",
        )


class _GrandfatherUnchangedMixin:
    """Shared helper: has this field's value actually changed on an update?

    Both field mixins below grandfather unchanged values, so the check lives
    here rather than being duplicated or inherited by accident from whichever
    mixin happens to be listed first.
    """

    def _is_unchanged(self, field, value):
        return self.instance is not None and getattr(self.instance, field, None) == value


class USContactFieldsMixin(_GrandfatherUnchangedMixin):
    """Validate phone/ZIP on create, and on update only when the value changed.

    Deliberately NOT attached to the model fields: 44 pre-existing rows hold junk
    like phone "213213" / zip "13", and the company edit modal echoes every stored
    value back on save. A blanket model validator would therefore reject an edit
    because of a field the grower never touched.

    Grandfathering an unchanged value keeps those edits working without letting
    anyone deliberately write NEW garbage into the field.

    Subclasses declare the fields they own:
        US_PHONE_FIELDS = ("contact_phone",)
        US_ZIP_FIELDS = ("zip_code",)
    """

    US_PHONE_FIELDS: tuple = ()
    US_ZIP_FIELDS: tuple = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)

        checks = [(field, validate_us_phone) for field in self.US_PHONE_FIELDS]
        checks += [(field, validate_us_zip) for field in self.US_ZIP_FIELDS]

        errors = {}
        for field, validator in checks:
            if field not in attrs:
                continue
            value = attrs[field]
            if self._is_unchanged(field, value):
                continue
            try:
                validator(value)
            except ValidationError as exc:
                errors[field] = list(exc.messages)

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class USStateFieldMixin(_GrandfatherUnchangedMixin):
    """Validate and canonicalize state fields on create, and on update when changed.

    Follows USContactFieldsMixin's grandfathering rule for the same reason —
    legacy rows hold values like "California" or "" and the edit modal echoes
    every stored value back on save, so a blanket model validator would reject
    an edit because of a field the grower never touched. The data migration
    normalizes what it can; this stops NEW unresolvable values being written.

    Resolvable values are rewritten to the canonical 2-letter code, so anything
    saved through the API is directly usable by the regional lookups.

    Subclasses declare the fields they own:
        US_STATE_FIELDS = ("state",)
    """

    US_STATE_FIELDS: tuple = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)

        errors = {}
        for field in self.US_STATE_FIELDS:
            if field not in attrs:
                continue
            value = attrs[field]
            if self._is_unchanged(field, value):
                continue
            try:
                validate_us_state(value)
            except ValidationError as exc:
                errors[field] = list(exc.messages)
                continue
            if value:
                attrs[field] = normalize_state(value)

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
