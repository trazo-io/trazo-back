"""
USDA forms #22 (Clean Transport Affidavit) and #25 (Adjoining Land Use Verification).

WHY (2026-08-12):

**#22** — Trazo recorded `clean_transport_method` ("how do you know the unit was clean":
affidavit / inspected / dedicated) and whether a document was attached. It never recorded what
that affidavit SAYS, so a certifier learned a file existed, not what it attested to. USDA asks
for the unit's prior load, the cleaning method, and the pre-load inspection findings. Of those
the prior load matters most: "swept" means little without knowing swept of what.

**#25** — a NEIGHBOUR-signed attestation, and therefore a separate model rather than more keys
on `Parcel.buffer_zones`. The two answer the same question from different authorities:

    buffer_zones            what the OPERATOR says about the boundary
    AdjoiningLandAffidavit  what the NEIGHBOUR signs about their own practices

Folding the second into the first would let an operator's own entry render as third-party
verification — the claim-shape failure this codebase has hit repeatedly.

Distance is in FEET because that is what USDA's form prints and what a neighbour says out
loud. `buffer_zones.buffer_width_m` is metres; silently mixing them turns a 25 ft buffer into
a 25 m one.
"""

import datetime
import io
import re
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone

from certifications.models import AdjoiningLandAffidavit
from company.models import Company, Establishment
from history.models import History, SalesRecord
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class TransportInspectionDisplayTests(TestCase):
    def test_renders_the_declared_findings(self):
        record = SalesRecord(transport_inspected_free_of=["foreign_odors", "residues"])
        self.assertEqual(record.transport_inspection_display(), "Free of foreign odors, Free of residues")

    def test_empty_is_empty_not_a_clean_finding(self):
        """An empty list is "no inspection recorded". Rendering it as "found clean" would be
        an attestation nobody made."""
        self.assertEqual(SalesRecord(transport_inspected_free_of=[]).transport_inspection_display(), "")

    def test_an_unknown_code_is_passed_through_not_dropped(self):
        """A stored value is evidence of something; discarding it edits the record."""
        record = SalesRecord(transport_inspected_free_of=["residues", "mystery_code"])
        self.assertEqual(record.transport_inspection_display(), "Free of residues, mystery_code")

    def test_tolerates_a_non_list_value(self):
        self.assertEqual(SalesRecord(transport_inspected_free_of=None).transport_inspection_display(), "")
        self.assertEqual(SalesRecord(transport_inspected_free_of={"a": 1}).transport_inspection_display(), "")


class TransportOtherNeedsNotesTests(TestCase):
    """ "Other" is the only answer on this form that carries no information by itself.

    Both labels that produce it print as "see notes" in the certifier packet
    ("Other — described in the notes" / "Other findings — see notes"), and until 0204 the model
    had no notes column at all: the packet pointed a certifier at a description that could not
    exist. Refuse the pointer without the target.
    """

    def _record(self, **kwargs):
        return SalesRecord(buyer_name="Buyer Co", sale_date=datetime.date(2026, 8, 1), quantity=10, **kwargs)

    def test_other_cleaning_method_without_notes_is_refused(self):
        with self.assertRaises(DjangoValidationError) as ctx:
            self._record(transport_cleaning_method="other").clean()
        self.assertIn("transport_notes", ctx.exception.message_dict)

    def test_other_inspection_finding_without_notes_is_refused(self):
        with self.assertRaises(DjangoValidationError) as ctx:
            self._record(transport_inspected_free_of=["residues", "other"]).clean()
        self.assertIn("transport_notes", ctx.exception.message_dict)

    def test_whitespace_is_not_a_description(self):
        with self.assertRaises(DjangoValidationError):
            self._record(transport_cleaning_method="other", transport_notes="   ").clean()

    def test_other_with_notes_is_accepted(self):
        self._record(transport_cleaning_method="other", transport_notes="Steam-cleaned at the yard").clean()

    def test_not_required_contradicts_a_non_dedicated_unit(self):
        """ "Not required — dedicated organic unit" is an answer about the unit BEING dedicated.

        Against affidavit/inspected — both of which describe a non-dedicated unit — it is
        self-contradictory, and the packet would print both halves as fact.
        """
        for method in ("affidavit", "inspected"):
            with self.subTest(clean_transport_method=method):
                with self.assertRaises(DjangoValidationError) as ctx:
                    self._record(
                        clean_transport_method=method,
                        transport_cleaning_method="not_required",
                    ).clean()
                self.assertIn("transport_cleaning_method", ctx.exception.message_dict)

    def test_not_required_is_fine_on_a_dedicated_unit(self):
        self._record(
            clean_transport_method="dedicated_organic",
            transport_cleaning_method="not_required",
        ).clean()

    def test_not_required_is_fine_when_clean_transport_is_unanswered(self):
        """Blank is 'not documented', not a claim of a non-dedicated unit — do not refuse it."""
        self._record(transport_cleaning_method="not_required").clean()

    def test_a_listed_option_never_requires_notes(self):
        """The guard must not spread to the answers that are already self-describing."""
        self._record(transport_cleaning_method="swept", transport_inspected_free_of=["residues"]).clean()


class SaleUnitVocabularyTests(TestCase):
    """The harvest unit and the sale unit must come from ONE list.

    They are the two halves of the mass balance, and the audit export prints the Balance line
    and the "sold exceeds harvest" review flag only when the two strings are equal. Before 0204
    `quantity_unit` was the one unit column with no `choices` and the editor had drifted to its
    own vocabulary — `tonnes` where harvest says `tons`, and no `crates` / `bushels` / `units`
    at all. Same weight, different string, and § 205.103(b)(2) reconciliation silently vanished
    from the packet with nothing printed to say it had.
    """

    #: Editor -> the const holding its unit dropdown. These are the two halves of the balance:
    #: one writes History.production_unit, the other SalesRecord.quantity_unit.
    APP_UNIT_LISTS = {
        "views/Dashboard/Dashboard/Production/SalesRecordsSection.tsx": "UNIT_CHOICES",
        "components/Forms/StandardFinishProductionForm.tsx": "UNIT_OPTIONS",
    }

    def test_sale_unit_choices_are_declared_from_the_harvest_list(self):
        """Narrow by design: it only catches someone replacing the reference with a literal.

        `quantity_unit` is declared `choices=History.UNIT_CHOICES`, so comparing the two here
        is true by construction and this assertion can never fail on drift. The drift that
        actually happened was in the FRONTEND, which is what the next test checks.
        """
        self.assertEqual(SalesRecord._meta.get_field("quantity_unit").choices, History.UNIT_CHOICES)

    def test_tonnes_is_gone(self):
        """It was only ever reachable through the one dropdown; 0204 folded it into `tons`."""
        self.assertNotIn("tonnes", dict(SalesRecord._meta.get_field("quantity_unit").choices))

    def test_both_editors_offer_exactly_the_backend_units(self):
        """The guard with teeth. Three lists, one vocabulary, checked across the repos.

        Nothing inside Django could see the real failure: the harvest form offered `tons` and
        the sales form offered `tonnes`, so a grower could not enter a sale in the unit they
        harvested in, and the packet's mass-balance section quietly emptied itself. Both halves
        live in trazo-app, which is why the existing registry guards — all of them
        registry-outbound — were structurally blind to it.
        """
        app_src = Path(__file__).resolve().parents[3] / "trazo-app" / "src"
        if not app_src.is_dir():
            # Do NOT silently pass; a guard that no-ops in half the checkouts is decorative.
            self.fail(f"trazo-app/src not found at {app_src}. This guard needs both repos.")

        expected = [value for value, _label in History.UNIT_CHOICES]
        for relative_path, const_name in self.APP_UNIT_LISTS.items():
            path = app_src / relative_path
            self.assertTrue(path.is_file(), f"{relative_path} not found — did the editor move?")
            source = path.read_text(encoding="utf8")
            opening = f"const {const_name} = ["
            start = source.find(opening)
            self.assertNotEqual(start, -1, f"{const_name} not found in {relative_path}")
            # Scope to THIS array: both files hold other `value:` lists (cleaning methods,
            # quality grades) that a whole-file scan would happily mix in.
            end = source.find("\n];", start)
            self.assertNotEqual(end, -1, f"{const_name} in {relative_path} is not closed by '];'")
            found = re.findall(r"value:\s*'([^']+)'", source[start:end])
            self.assertEqual(
                found,
                expected,
                f"{relative_path} :: {const_name} must offer exactly History.UNIT_CHOICES, in "
                f"the same order. Adding or renaming a unit means changing all three lists in "
                f"one commit.",
            )


class AdjoiningLandAffidavitModelTests(TestCase):
    def test_materials_display_is_empty_when_unanswered(self):
        """Empty list = not answered. The affirmative "none" lives in declares_no_materials."""
        self.assertEqual(AdjoiningLandAffidavit(materials_used=[]).materials_display(), "")

    def test_materials_display_labels_known_codes(self):
        affidavit = AdjoiningLandAffidavit(materials_used=["herbicides", "treated_wood"])
        self.assertEqual(affidavit.materials_display(), "Herbicides, Treated wood")

    def test_is_signed_requires_a_signature_or_a_document(self):
        self.assertFalse(AdjoiningLandAffidavit().is_signed())
        self.assertTrue(AdjoiningLandAffidavit(neighbor_signed_date=datetime.date(2026, 3, 1)).is_signed())

    def test_unanswered_organic_status_is_not_a_denial(self):
        """NULL means the neighbour did not answer, not that they are conventional."""
        self.assertIsNone(AdjoiningLandAffidavit().neighbor_is_certified_organic)


class AdjoiningLandAffidavitSerializerTests(TestCase):
    """Write-boundary guards. The packet renders unknown codes verbatim on purpose — a stored
    value is evidence of something — so the validation has to happen on the way in."""

    def setUp(self):
        company = Company.objects.create(name="Ser Co")
        establishment = Establishment.objects.create(name="S1", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)

    def _serializer(self, **overrides):
        from certifications.serializers import AdjoiningLandAffidavitSerializer

        data = {"parcel": self.parcel.id, "neighbor_name": "R. Neighbour"}
        data.update(overrides)
        return AdjoiningLandAffidavitSerializer(data=data)

    def test_accepts_known_material_codes(self):
        serializer = self._serializer(materials_used=["herbicides", "treated_wood"])
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_an_unknown_material_code(self):
        serializer = self._serializer(materials_used=["weedkiller"])
        self.assertFalse(serializer.is_valid())
        self.assertIn("materials_used", serializer.errors)

    def test_rejects_a_non_list_materials_value(self):
        serializer = self._serializer(materials_used="herbicides")
        self.assertFalse(serializer.is_valid())

    def test_rejects_declaring_none_while_listing_materials(self):
        """A signed "none of the above" over a list of materials is a contradictory
        attestation; the packet would have to print both halves."""
        serializer = self._serializer(materials_used=["herbicides"], declares_no_materials=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("declares_no_materials", serializer.errors)

    def test_declaring_none_on_its_own_is_fine(self):
        self.assertTrue(self._serializer(declares_no_materials=True).is_valid())


class TransportAndAdjoiningPacketTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="tr@test.com", password="x")
        company = Company.objects.create(name="TR Co")
        establishment = Establishment.objects.create(name="TR1", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="TR Production",
            start_date=timezone.now(),
            product=product,
            parcel=self.parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def _sale(self, **kwargs):
        defaults = dict(
            production=self.history,
            buyer_name="Buyer Co",
            sale_date=datetime.date(2026, 8, 1),
            vehicle_id="TRK-1",
            # NOT NULL on the model — omitting it fails the insert, not the assertion.
            quantity=1000,
        )
        defaults.update(kwargs)
        return SalesRecord.objects.create(**defaults)

    def test_the_affidavit_content_reaches_the_paper(self):
        self._sale(
            clean_transport_method="inspected",
            prior_products_transported="Conventional almonds",
            transport_cleaning_method="swept",
            transport_inspected_free_of=["foreign_odors", "residues"],
        )
        text = self._text()
        self.assertIn("previously carried: Conventional almonds", text)
        self.assertIn("cleaning: Swept", text)
        self.assertIn("inspected: Free of foreign odors, Free of residues", text)

    def test_the_other_description_reaches_the_paper(self):
        """The packet prints "Other — described in the notes"; the notes must follow it."""
        self._sale(
            clean_transport_method="inspected",
            prior_products_transported="Conventional almonds",
            transport_cleaning_method="other",
            transport_notes="Steam-cleaned at the Hughson yard",
        )
        text = self._text()
        self.assertIn("cleaning: Other", text)
        self.assertIn("notes: Steam-cleaned at the Hughson yard", text)

    def test_affidavit_answers_reach_the_paper_without_shipping_identifiers(self):
        """Answering form #22 must be enough on its own.

        The whole per-shipment block used to be gated on BOL / carrier / vehicle / destination /
        clean-transport, so a grower who filled in the cleaning method, the inspection and the
        notes but none of the shipping identifiers got nothing at all — including the notes the
        "Other" labels promise a certifier they will find.
        """
        self._sale(
            vehicle_id="",
            transport_cleaning_method="other",
            transport_notes="Steam-cleaned at the yard",
            transport_inspected_free_of=["residues"],
        )
        text = self._text()
        self.assertIn("cleaning: Other", text)
        self.assertIn("notes: Steam-cleaned at the yard", text)
        self.assertIn("inspected: Free of residues", text)

    def test_mass_balance_reconciles_when_the_sale_unit_matches_the_harvest_unit(self):
        """The whole point of the shared unit vocabulary.

        The Balance line and the excess-sale flag are gated on `harvest_unit == sold_unit`, so a
        sale unit the harvest form cannot produce removed both from the packet SILENTLY — no
        warning, just an absent section. Assert the positive: matching units reconcile, and an
        oversold lot is caught.
        """
        self.history.production_amount = 1000
        self.history.production_unit = "lb"
        self.history.save(update_fields=["production_amount", "production_unit"])
        self._sale(quantity=2000, quantity_unit="lb")
        text = self._text()
        # No harvest record: the organic lot's balance is not computed, as on the trace, and the
        # header total still catches the oversold lot (overall review 2026-11, OV-FJ-C24).
        self.assertIn("Organic lot: harvested minus sold", text)
        self.assertIn("Balance not computed: no harvest record is on file for this season", text)
        self.assertIn("EXCEEDS harvest yield", text)

    def test_a_non_dedicated_unit_without_a_prior_load_is_flagged(self):
        """ "Swept" means little without knowing swept of what."""
        self._sale(clean_transport_method="inspected", transport_cleaning_method="swept")
        text = self._text()
        self.assertIn("without recording what it carried immediately before", text)

    def test_a_dedicated_organic_unit_is_not_asked_for_a_prior_load(self):
        """A dedicated unit has no prior conventional load; demanding one would be Trazo
        inventing a requirement."""
        self._sale(clean_transport_method="dedicated_organic")
        self.assertNotIn("without recording what it carried immediately before", self._text())

    def test_neighbour_attestation_renders_with_distance_in_feet(self):
        AdjoiningLandAffidavit.objects.create(
            parcel=self.parcel,
            neighbor_name="R. Neighbour",
            border_side="N",
            materials_used=["herbicides"],
            distance_to_organic_property_ft=150,
            agrees_to_notify=True,
            neighbor_signed_date=datetime.date(2026, 3, 1),
        )
        text = self._text()
        self.assertIn("Adjoining Land Use Verification", text)
        self.assertIn("R. Neighbour", text)
        self.assertIn("150 ft", text)
        self.assertIn("Herbicides", text)

    def test_an_unsigned_attestation_is_marked_and_flagged(self):
        """Unsigned, it is the operation's account of a neighbour's practices — not
        third-party verification of them."""
        AdjoiningLandAffidavit.objects.create(parcel=self.parcel, neighbor_name="S. Unsigned", border_side="S")
        text = self._text()
        self.assertIn("UNSIGNED", text)
        self.assertIn("not signed by the neighbour", text)

    def test_an_unanswered_notify_question_is_not_rendered_as_a_refusal(self):
        """A neighbour who did not answer has not refused to notify."""
        AdjoiningLandAffidavit.objects.create(
            parcel=self.parcel,
            neighbor_name="T. Silent",
            neighbor_signed_date=datetime.date(2026, 3, 1),
        )
        self.assertIn("Not answered", self._text())

    def test_a_declared_none_reads_differently_from_silence(self):
        AdjoiningLandAffidavit.objects.create(
            parcel=self.parcel,
            neighbor_name="U. Clean",
            declares_no_materials=True,
            neighbor_signed_date=datetime.date(2026, 3, 1),
        )
        self.assertIn("None of the listed materials (declared)", self._text())

    def test_stays_silent_when_no_neighbour_attestation_exists(self):
        """No section at all rather than an empty table, which would read as a finding."""
        self.assertNotIn("Adjoining Land Use Verification", self._text())
