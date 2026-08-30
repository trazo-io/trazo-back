"""The off-farm handler record must reach the plan layer, not only the audit export.

WHY THIS EXISTS
---------------
The largest blocker in the certifier conformance register: **6 rows across both certifiers**
(CCOF G6.1 C1/C2, CCOF G6.2 A, WSDA J 13, K 1, L 1). `PostHarvestFacility` has always held the
handler's name, address, type, certifier, certificate number and dates, and computed a
`cert_is_current` tri-state — and no OSP module read any of it. The plan answered "who handles or
stores your crop" from free text while the structured record lived in a separate download, so the
pilot packet named the same handler as "Eugene DC" in one place and "Portland DC" in another,
under one certificate number, with nothing comparing them.

CCOF asks it as a table with the certificate attached. WSDA gates whole required sections on it —
J13, K1 and L1 are first questions with no skip, and a "Yes" there declares an attached AGR 2519.
An unanswered gate is a bounce, not a request for information.

Three things must hold together, which is why they are tested together:
  1. the gates EXIST, so "no" is a complete answer a reviewer can read;
  2. the record REACHES the module PDF (an `embed` that renders nothing is the defect this
     codebase has now hit four times);
  3. the record REACHES the (a)(5) narrative, which is what a certifier reads first.

The certificate line states only what the record supports: `cert_is_current` is None when there is
no effective date, and that must print as "not stated", never as current.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.osp_modules import MODULE_REGISTRY
from certifications.services.osp_module_compiler import compile_module_contributions
from company.models import Company, Establishment


def _module(key):
    return next(m for m in MODULE_REGISTRY if m.key == key)


def _questions(module_key):
    return {q.key: q for page in _module(module_key).pages for q in page.questions}


class TheGatesExist(TestCase):
    """A form Trazo cannot answer at all is worse than one it answers badly."""

    def test_g6_1_asks_whether_the_crop_is_handled_off_the_farm(self):
        q = _questions("g6_1_harvest_transport").get("handled_by_another_operation")
        self.assertIsNotNone(q, "CCOF G6.1 §C is a routing gate; Trazo must ask it")
        values = {o.value for o in q.options}
        self.assertIn("no", values, "'No' must be an answerable, complete answer")
        self.assertTrue(
            {"yes_certified", "yes_uncertified"} <= values,
            "certified vs uncertified changes whose records carry the audit trail",
        )

    def test_g6_2_asks_whether_a_third_party_stores_the_crop(self):
        # WSDA K1. `commercial_cold_off_farm` cannot distinguish "we rent a unit" from
        # "another operation stores for us", and only the second puts the crop in someone
        # else's records.
        self.assertIn("third_party_storage_contracted", _questions("g6_2_storage"))

    def test_both_gates_open_the_same_facility_record(self):
        # One record, two questions — the reason the handler and storage defects were merged.
        g61 = _questions("g6_1_harvest_transport")["off_farm_handler_table"]
        g62 = _questions("g6_2_storage")["off_farm_storage_table"]
        self.assertEqual(g61.embed, "post_harvest_facilities")
        self.assertEqual(g62.embed, "post_harvest_facilities")

    def test_the_facility_record_carries_a_role(self):
        # A cold store either holds the crop or also packs it. Without this axis one row has
        # to answer both CCOF forms or neither.
        self.assertEqual(
            {c[0] for c in PostHarvestFacility.ROLE_CHOICES},
            {"handling", "storage", "both"},
        )


class TheRecordReachesTheDocuments(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Handler Co")
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.facility = PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Organically Grown Company",
            facility_type="cold_storage",
            role="both",
            address="7150 NE Portland Hwy",
            city="Portland",
            state="OR",
            certification_number="OTCO-0042",
            certifier_name="Oregon Tilth Certified Organic",
            effective_date=timezone.now().date() - timedelta(days=30),
        )

    def _narrative(self):
        contributions = compile_module_contributions(self.osp)
        return "\n".join(contributions.get("commingling_barriers", []))

    def test_the_handler_is_named_in_the_a5_narrative(self):
        text = self._narrative()
        self.assertIn("Organically Grown Company", text)
        self.assertIn("Portland", text)
        self.assertIn("OTCO-0042", text)

    def test_a_current_certificate_is_stated_as_current(self):
        self.assertIn("organic certificate current", self._narrative())

    def test_a_certificate_with_no_date_is_not_called_current(self):
        # `cert_is_current` returns None here. The old failure mode across this codebase is
        # absence read as a positive verdict.
        self.facility.effective_date = None
        self.facility.save(update_fields=["effective_date"])
        text = self._narrative()
        self.assertIn("date not stated", text)
        self.assertNotIn("certificate current", text)

    def test_an_expired_certificate_says_so(self):
        self.facility.effective_date = timezone.now().date() - timedelta(days=900)
        self.facility.save(update_fields=["effective_date"])
        self.assertIn("expired or older than 15 months", self._narrative())

    def test_a_facility_with_no_certificate_at_all_is_flagged_not_omitted(self):
        self.facility.certification_number = ""
        self.facility.certifier_name = ""
        self.facility.save(update_fields=["certification_number", "certifier_name"])
        self.assertIn("no organic certificate on file", self._narrative())

    def test_the_narrative_states_the_RECORD_not_a_conclusion(self):
        """Caught reviewing my own first cut of this feature (2026-08-28).

        It opened "This operation's crop is handled or stored off the farm by the following
        facilities" — a conclusion. A farm whose operator answered the gate "no, nobody off this
        operation handles our crop" but still carries facility rows from an earlier season would
        have had its own plan contradict its own answer, over the producer's name. The paragraph
        reports the file; the gate's answer is compiled separately from the operator's own words.
        """
        text = self._narrative()
        self.assertIn("on file for this operation", text)
        self.assertNotIn("This operation's crop is handled", text)

    def test_an_unstated_role_prints_nothing_rather_than_a_default(self):
        """Also caught on the second read: `role` first defaulted to "handling".

        Every row that existed before the field did would have printed "Handles the crop (packs,
        hulls, dries, conditions)" — including a cold store nobody described that way. Same
        absence-as-a-positive-verdict class as `cert_is_current`: unset prints as unset.
        """
        self.facility.role = ""
        self.facility.save(update_fields=["role"])
        text = self._narrative()
        self.assertIn("Organically Grown Company", text)
        self.assertNotIn("Handles the crop", text)
        self.assertNotIn("Stores the crop", text)

    def test_the_shipped_default_for_role_is_unstated(self):
        # Anti-vacuity for the test above: if the field default were "handling" again, a newly
        # created facility would assert a role nobody chose and the test above would still pass
        # because it sets the field by hand.
        fresh = PostHarvestFacility.objects.create(establishment=self.est, name="Unasked Co")
        self.assertEqual(fresh.role, "")

    def test_an_operation_with_no_facilities_adds_nothing(self):
        # Anti-overreach: the paragraph must not appear on a farm that has no handler, or
        # every plan would carry an empty heading.
        self.facility.delete()
        self.assertNotIn("Off-farm handlers", self._narrative())

    def test_the_module_pdf_renders_the_table(self):
        from certifications.services.osp_module_pdf import _post_harvest_facility_flowables

        class _S(dict):
            def __missing__(self, k):
                from reportlab.lib.styles import getSampleStyleSheet

                return getSampleStyleSheet()["Normal"]

        rendered = _post_harvest_facility_flowables(self.osp, _S())
        text = " ".join(getattr(f, "text", "") for f in rendered)
        self.assertIn("Organically Grown Company", text)
        self.assertIn("OTCO-0042", text)

    def test_the_pdf_says_the_certificate_document_is_not_embedded(self):
        # The audit export already refuses to imply an attachment it does not carry; the plan
        # must not imply one either. CCOF G6.1 C3 asks for the certificate ATTACHED.
        from certifications.services.osp_module_pdf import _post_harvest_facility_flowables

        class _S(dict):
            def __missing__(self, k):
                from reportlab.lib.styles import getSampleStyleSheet

                return getSampleStyleSheet()["Normal"]

        text = " ".join(getattr(f, "text", "") for f in _post_harvest_facility_flowables(self.osp, _S()))
        self.assertIn("not embedded", text)
