"""A WSDA listing is evidence the record can hold, and it speaks in WSDA's name.

Until 2026-09-02 `wsda_listed` was selectable in the activity form and was already in the
audit export's third-party basis set — but `ChemicalEvent` had no WSDA column. So the claim
could be MADE and never BACKED: the certifier dossier appended "grower-selected, no listing on
file" forever, and `may_claim_input_listing` dropped the input to grower-reported on the buyer
page, even when the product sat in the WSDA catalogue Trazo already ships.

That is not a rounding error. 23 of the 42 seeded WSDA brands have no OMRI counterpart
(Feather Meal 13-0-0, AzaMax, Kaligreen, Madex HP …), and CCOF accepts a WSDA registration in
place of an OMRI listing. It also created a bad incentive: with six selectable OMRI rows beside
one unselectable WSDA row, a grower chasing the stronger chip was pushed toward attaching a
neighbouring OMRI listing for a product they had not applied — the exact failure
`consumer-omri-listing-leak-2026-08-09` exists to prevent.
"""

from types import SimpleNamespace

from django.test import TestCase

from certifications.models import OMRIProduct, WSDAMaterial
from history.services.audit_export_service import _organic_basis_cell
from history.services.claim_authority import (
    LABEL_INPUT_GROWER_REPORTED,
    LABEL_INPUT_OMRI_LISTED,
    LABEL_INPUT_WSDA_LISTED,
    may_claim_input_listing,
)
from history.services.claim_resolver import resolve_input_status


class _Event:
    """The three fields every decider under test reads. Avoids a full event fixture."""

    def __init__(self, omri=None, wsda=None, basis="wsda_listed"):
        self.omri_product_id = omri
        # `claim_authority` reads `delisted_on` off the related row: an OMRI FK earns the
        # claim only while OMRI still lists the product. A real event always resolves it.
        self.omri_product = SimpleNamespace(delisted_on=None) if omri else None
        self.wsda_material_id = wsda
        self.national_list_substance = None
        self.organic_approved = basis
        self.restricted_use_pesticide = False


class WSDAListingAttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.wsda = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-FERT-2025-001",
            brand_name="Neptune's Harvest Fish & Seaweed 2-3-1",
            category="fertilizer",
        )
        cls.omri = OMRIProduct.objects.create(
            omri_id="nhf-3041",
            product_name="Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1",
            category="crop-fertilizer",
        )

    def test_an_attached_wsda_listing_is_earned_evidence(self):
        decision = may_claim_input_listing(_Event(wsda=self.wsda.pk))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_WSDA_LISTED)

    def test_it_is_never_spoken_as_an_omri_listing(self):
        """Two organisations, two determinations. OMRI did not review this product."""
        label = may_claim_input_listing(_Event(wsda=self.wsda.pk)).safe_label
        self.assertNotEqual(label, LABEL_INPUT_OMRI_LISTED)
        self.assertNotIn("OMRI", label)

    def test_declaring_wsda_without_attaching_is_still_only_the_growers_word(self):
        decision = may_claim_input_listing(_Event())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_GROWER_REPORTED)

    def test_the_dossier_stops_appending_no_listing_on_file(self):
        self.assertEqual(_organic_basis_cell(_Event(wsda=self.wsda.pk)), "WSDA Listed")

    def test_the_dossier_still_discloses_an_unbacked_declaration(self):
        self.assertEqual(
            _organic_basis_cell(_Event()),
            "WSDA Listed — grower-selected, no listing on file",
        )

    def test_the_consumer_chip_carries_its_own_status(self):
        self.assertEqual(
            resolve_input_status(_Event(wsda=self.wsda.pk)),
            {"status": "wsda_listed", "label": LABEL_INPUT_WSDA_LISTED},
        )

    def test_omri_still_outranks_wsda_when_both_are_attached(self):
        """Not a value judgement — just one label per chip, and OMRI is the wider-recognised one."""
        decision = may_claim_input_listing(_Event(omri=self.omri.pk, wsda=self.wsda.pk))
        self.assertEqual(decision.safe_label, LABEL_INPUT_OMRI_LISTED)

    def test_the_event_can_actually_store_it(self):
        """The field exists and is nullable — the gap this whole file is about."""
        from history.models import ChemicalEvent

        field = ChemicalEvent._meta.get_field("wsda_material")
        self.assertTrue(field.null)
        self.assertEqual(field.related_model, WSDAMaterial)

    def test_both_chemical_serializers_expose_it(self):
        """A field the API cannot round-trip is a field the grower cannot attach."""
        from history.serializers import ChemicalEventSerializer, UpdateChemicalEventSerializer

        for serializer in (ChemicalEventSerializer, UpdateChemicalEventSerializer):
            self.assertIn("wsda_material", serializer.Meta.fields, serializer.__name__)


class WSDAAggregateBucketTests(TestCase):
    """A WSDA listing counts as CATALOG evidence in the buyer page's summary line.

    The bucketing in `transparency_views` matched `LABEL_INPUT_OMRI_LISTED` and let everything
    else fall into an `else` branch labelled "the grower's own dropdown, or unclassified".
    A new evidence label therefore landed in `grower_reported` — reporting the grower's word
    for an input Trazo holds a third-party listing for, which is that branch's own rule
    inverted. Found reading the diff back on 2026-09-02, not by a failing test.
    """

    def test_every_earned_listing_label_has_a_catalog_bucket(self):
        import inspect

        from history import transparency_views
        from history.services.claim_authority import LABEL_INPUT_OMRI_LISTED, LABEL_INPUT_WSDA_LISTED

        source = inspect.getsource(transparency_views)
        start = source.index('counts = {"catalog_matched"')
        block = source[start:][:2000]
        for label_name in ("LABEL_INPUT_OMRI_LISTED", "LABEL_INPUT_WSDA_LISTED"):
            self.assertIn(
                label_name,
                block,
                f"{label_name} is an EARNED catalog listing but the summary never routes it — "
                "it would be counted as grower_reported",
            )
        # And they share the one bucket rather than each inventing a tier.
        self.assertIn("catalog_matched", block)
        del LABEL_INPUT_OMRI_LISTED, LABEL_INPUT_WSDA_LISTED
