"""A web form becomes a form-inventory source the same way a PDF does: hashed, dated, re-derivable.

WHY THIS EXISTS
---------------
CCOF's annual renewal contract (registered 2026-10-01, OSP alignment audit T20) is a Gravity Form
on ccof.org, not a document. The page carries per-request nonces, so hashing the page would give a
new "edition" on every fetch, and a register tied to a hash that cannot be reproduced proves
nothing. The capture keeps the one form, drops what changes per request, and records the URL and
date, which stands in for the revision a web form does not print.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from certifications.services.certifier_register import _filing_meta
from certifications.services.form_inventory import capture_gravity_form, extract_items, extract_revision, sha256_of


def _page(nonce: str) -> str:
    # The per-request inputs sit inside a field the capture keeps (as they do in a form with no
    # CAPTCHA, where the footer falls into the last real field), so stripping them is exercised.
    return f"""<html><body><form id='search'></form>
<form method='post' id='gform_5' action='/payments/#gf_5'>
<div id="field_5_45" class="gfield gfield--type-honeypot"><label class='gfield_label gform-field-label'>X/Twitter</label></div>
<fieldset id="field_5_1" class="gfield gfield--type-radio gfield_contains_required"><legend class='gfield_label'>Step 1: Request Renewal<span>(Required)</span></legend>
<label for='choice_5_1_0' id='label_5_1_0'>I wish to continue certification.</label>
<label for='choice_5_1_1' id='label_5_1_1'>I no longer require certification.</label></fieldset>
<div id="field_5_7" class="gfield gfield--type-text"><label class='gfield_label gform-field-label'>Client Code</label></div>
<div id="field_5_36" class="gfield gfield--type-html">By checking you are stating that: 1. You affirm the plan is accurate. 2. You will pay all fees.</div>
<input type='hidden' name='gform_unique_id' value='{nonce}' />
<input type='hidden' name='state_5' value='{nonce}{nonce}' />
<div id="field_5_39" class="gfield gfield--type-captcha"><label class='gfield_label gform-field-label'>CAPTCHA</label></div>
</form></body></html>"""


class CaptureTests(SimpleTestCase):
    def _capture(self, nonce: str, folder: Path) -> Path:
        path = folder / f"capture-{nonce}.html"
        path.write_text(capture_gravity_form(_page(nonce), "5", "https://example.org/payments/", "2026-10-01"))
        return path

    def test_two_fetches_of_an_unchanged_form_hash_the_same(self):
        with TemporaryDirectory() as tmp:
            first = self._capture("aaa111", Path(tmp))
            second = self._capture("zzz999", Path(tmp))
            self.assertEqual(sha256_of(first), sha256_of(second))
            text = first.read_text()
            for volatile in ("aaa111", "honeypot", "captcha", "gform_unique_id"):
                self.assertNotIn(volatile, text)

    def test_the_capture_date_is_the_edition(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(extract_revision(self._capture("n", Path(tmp))), "2026-10-01")

    def test_items_are_questions_and_numbered_terms_in_form_order(self):
        with TemporaryDirectory() as tmp:
            items = extract_items("ccof", self._capture("n", Path(tmp)))
        self.assertEqual(
            [(i.ref, i.kind, i.optional) for i in items],
            [
                ("Step 1: Request Renewal", "question", False),
                ("Client Code", "question", True),
                ("1", "instruction", False),
                ("2", "instruction", False),
            ],
        )
        self.assertIn("I no longer require certification", items[0].text)


class NumberedTermsTests(SimpleTestCase):
    """Every numbered term of an HTML block is its own instruction, preamble or not (review of
    back #80: a block opening on "1." lost term 1, and a two-term block lost its numbering)."""

    def _items(self, html_text: str):
        capture = (
            "<!-- captured 2026-10-01 from https://example.org/ (Gravity Form gform_5) -->\n"
            f'<div id="field_5_36" class="gfield gfield--type-html">{html_text}</div>\n'
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.html"
            path.write_text(capture)
            return [(i.ref, i.kind) for i in extract_items("ccof", path)]

    def test_a_block_that_opens_on_its_first_number_keeps_term_one(self):
        self.assertEqual(
            self._items("1. You affirm the plan. 2. You pay fees. 3. You comply."),
            [("1", "instruction"), ("2", "instruction"), ("3", "instruction")],
        )

    def test_two_terms_without_a_preamble_keep_their_numbers(self):
        self.assertEqual(self._items("1. You affirm. 2. You pay."), [("1", "instruction"), ("2", "instruction")])

    def test_a_preamble_is_not_a_term(self):
        self.assertEqual(
            self._items("By checking you state that: 1. You affirm. 2. You pay."),
            [("1", "instruction"), ("2", "instruction")],
        )

    def test_an_unnumbered_block_is_one_instruction(self):
        self.assertEqual(len(self._items("New certificates are issued in January.")), 1)


class RenewalRoleIsAgentPaperworkTests(SimpleTestCase):
    def test_a_renewal_role_on_a_form_not_filed_with_the_agent_is_refused(self):
        with self.assertRaises(ValueError):
            _filing_meta({"renewal_role": "fee"}, "x.yaml")

    def test_an_unknown_renewal_role_is_refused(self):
        with self.assertRaises(ValueError):
            _filing_meta({"renewal_role": "renewal", "filed_with_agent": True}, "x.yaml")
