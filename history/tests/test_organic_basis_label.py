"""The verification-basis column prints an enum label or nothing — never a raw value.

`organic_approved` / `amendment_organic_approved` are CharFields with `choices`, and Django
does not enforce choices on `.save()` — nor does `get_..._display()` reject an unknown value:
it falls straight through to the raw string. A seeding script that wrote a Python `True`
therefore printed "Organic Status: True" on a live certifier packet, in the column an
inspector reads as the § 205.203(b) / § 205.601 basis for using the input.

"True" asserts approval and names no listing, no seal and no certifier. It is exactly the
class of claim the packet is built to refuse.
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import _organic_basis_label


class OrganicBasisLabelTests(SimpleTestCase):
    def test_a_recognised_basis_renders_its_label(self):
        self.assertEqual(_organic_basis_label("omri_listed"), "OMRI Listed")

    def test_a_legacy_value_still_renders_rather_than_showing_a_slug(self):
        self.assertIn("Yes", _organic_basis_label("yes"))

    def test_a_stringified_boolean_is_not_a_basis(self):
        label = _organic_basis_label("True")
        self.assertTrue(label.startswith("NOT SPECIFIED"))
        self.assertIn("True", label)  # the operator's raw value is disclosed, not discarded

    def test_an_arbitrary_string_is_not_a_basis(self):
        self.assertTrue(_organic_basis_label("approved by me").startswith("NOT SPECIFIED"))

    def test_nothing_recorded_returns_none_so_callers_can_say_so_themselves(self):
        self.assertIsNone(_organic_basis_label(None))
        self.assertIsNone(_organic_basis_label(""))
        self.assertIsNone(_organic_basis_label("   "))
