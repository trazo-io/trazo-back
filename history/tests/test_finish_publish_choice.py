"""
Publishing the buyer page is the farmer's choice at finish time (2026-08-16).

`History.finish()` used to set `published = True` unconditionally, so finishing a
production always pushed the buyer page live. The landing site meanwhile promised
"Nothing is public until you finish the production AND CHOOSE to publish it" — the
second half of which was not true of any code path. The finish dialog now carries a
checked-by-default checkbox and sends `published`.

Two failure modes these tests exist to catch, both of which publish a season the
farmer declined:

  1. The value crosses a multipart boundary, so it arrives as the STRING "false".
     `bool("false")` is True — the naive read republishes every unchecked box.
  2. A caller that predates the checkbox sends no key at all. That must keep
     publishing, or every direct-API finish silently goes dark.
"""

from django.test import TestCase

from history.models import _parse_publish_flag


class ParsePublishFlagTests(TestCase):
    """The parse in isolation. The values here are the ones a QueryDict really yields."""

    def test_absent_key_publishes(self):
        """Back-compat: every caller predating the checkbox must keep publishing."""
        self.assertIs(_parse_publish_flag(None), True)

    def test_multipart_string_false_does_not_publish(self):
        """The whole reason this helper exists — bool("false") is True."""
        self.assertIs(_parse_publish_flag("false"), False)

    def test_multipart_string_true_publishes(self):
        self.assertIs(_parse_publish_flag("true"), True)

    def test_real_booleans_pass_through(self):
        """JSON callers (DRF parses these to real bools) must work too."""
        self.assertIs(_parse_publish_flag(True), True)
        self.assertIs(_parse_publish_flag(False), False)

    def test_casing_and_alternate_negatives(self):
        for raw in ("False", "FALSE", "0", "off", "no", ""):
            self.assertIs(_parse_publish_flag(raw), False, f"{raw!r} should withhold")

    def test_unrecognised_value_publishes(self):
        """Ambiguity resolves to the historical behaviour, not to silently hiding."""
        self.assertIs(_parse_publish_flag("garbage"), True)
        self.assertIs(_parse_publish_flag("1"), True)
        self.assertIs(_parse_publish_flag("on"), True)
