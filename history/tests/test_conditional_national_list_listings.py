"""A conditional § 205.602 listing is not a prohibition — on any surface.

Three entries on 7 CFR 205.602 are conditional rather than absolute: the CFR bans the
substance EXCEPT for one named use. Calcium chloride (brine process) is the live one —
"prohibited ... except as a foliar spray to treat a physiological disorder associated with
calcium uptake", which is precisely the bitter-pit calcium programme every organic Honeycrisp
block in Washington runs, seven sprays from fruit set to ten days before the first pick.

Found 2026-08-20 on a two-farm rehearsal. Four surfaces read `status == "prohibited"` with no
test for the annotation, and each got it wrong in a different way:

  * the lot-level organic gate revoked the entire lot's organic claim and published
    "this lot: not represented as organic" to shoppers,
  * the consumer chip called a compliant organic input "Conventional input · documented",
  * the aggregate evidence tier filed it as `contradicted`,
  * and the certifier packet printed a flat PROHIBITED under a [WARNING] telling the
    certifier the crop was disqualified from organic sale.

The first fix attempt tested `if restriction_notes:` — presence of prose. That is worse than
the bug: § 205.105 rows carry notes too ("Glyphosate — Synthetic herbicide; not on § 205.601"),
so glyphosate would have been softened to "Restricted use" and moved out of the packet's
[WARNING] block. The distinction is TYPED on the row (`annotation_kind`) and every surface
must ask `is_conditionally_permitted`, never read the prose.
"""

from django.test import TestCase

from certifications.models import NationalListSubstance


class ConditionalListingTypingTests(TestCase):
    """The typed field, and the seeded data behind it."""

    def test_calcium_chloride_is_conditional_and_glyphosate_is_not(self):
        cacl = NationalListSubstance(
            substance_name="Calcium chloride (brine process)",
            cfr_section="205.602",
            status="prohibited",
            restriction_notes="Allowed only as foliar spray for calcium uptake disorders.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        glypho = NationalListSubstance(
            substance_name="Glyphosate",
            cfr_section="205.105",
            status="prohibited",
            restriction_notes="Synthetic herbicide; not on § 205.601 (NOP 5034-2).",
            annotation_kind=NationalListSubstance.ANNOTATION_RATIONALE,
        )

        self.assertTrue(cacl.is_conditionally_permitted)
        self.assertFalse(glypho.is_conditionally_permitted)

        # The regression guard proper: both rows carry prose, so any surface that tests for
        # the PRESENCE of restriction_notes cannot tell these two apart.
        self.assertTrue(cacl.restriction_notes)
        self.assertTrue(glypho.restriction_notes)

    def test_an_allowed_row_is_never_conditionally_permitted(self):
        """`is_conditionally_permitted` softens a prohibition; it says nothing about allowances.

        A § 205.601 row with a use restriction is already allowed — routing it through the
        conditional branch would downgrade "Allowed" to "Restricted use" in the packet.
        """
        spinosad = NationalListSubstance(
            substance_name="Spinosad",
            cfr_section="205.601",
            status="allowed",
            restriction_notes="Direct contact with soil or plant roots prohibited.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        self.assertFalse(spinosad.is_conditionally_permitted)

    def test_seeder_types_every_annotated_row(self):
        """No annotated row may be left at the `none` default by the seeder.

        A row that keeps the default is invisible to every surface's conditional branch, so a
        newly-added § 205.602 exception would silently regress to the flat-prohibited verdict
        this whole module exists to prevent.
        """
        from django.core.management import call_command

        call_command("seed_national_list", verbosity=0)

        untyped = (
            NationalListSubstance.objects.exclude(
                restriction_notes__isnull=True,
            )
            .exclude(
                restriction_notes="",
            )
            .filter(
                annotation_kind=NationalListSubstance.ANNOTATION_NONE,
            )
        )
        self.assertFalse(
            untyped.exists(),
            f"annotated rows left untyped: {list(untyped.values_list('substance_name', flat=True))}",
        )

        # And the § 205.105 block must never be typed as a condition of use.
        softened = NationalListSubstance.objects.filter(
            cfr_section="205.105",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        self.assertFalse(
            softened.exists(),
            "a § 205.105 note explains why a substance is banned; it grants no allowance: "
            f"{list(softened.values_list('substance_name', flat=True))}",
        )


class ConditionalListingConsumerSurfaceTests(TestCase):
    """The three consumer-side surfaces that read `status == "prohibited"` directly."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from carbon.models import CropType
        from company.models import Company, Establishment
        from history.models import ChemicalEvent, Production
        from product.models import Parcel, Product

        company = Company.objects.create(name="Cond Co")
        est = Establishment.objects.create(name="Cond Farm", company=company)
        parcel = Parcel.objects.create(name="Block", establishment=est, area=11.5)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-cond",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.history = Production.objects.create(
            parcel=parcel,
            product=Product.objects.create(name="Apple"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
        )
        self.cacl = NationalListSubstance.objects.create(
            substance_name="Calcium chloride (brine process)",
            substance_name_normalized="calcium chloride (brine process)",
            cfr_section="205.602",
            status="prohibited",
            restriction_notes="Allowed only as foliar spray for calcium uptake disorders.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        self.event = ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now() - timedelta(days=60),
            description="Calcium chloride 33% application",
            commercial_name="Calcium chloride 33%",
            target_pest_disease="Bitter pit prevention",
            national_list_substance=self.cacl,
            national_list_basis="operator",
            organic_approved="omri_listed",
        )

    def test_the_public_chip_does_not_call_it_a_conventional_input(self):
        """What shoppers read on the card.

        "Conventional input · documented" on a certified organic block's bitter-pit calcium
        programme is false in the damaging direction — it reports a nonconformance the farm
        did not commit, over the one use the regulation writes out as permitted.
        """
        from history.services.claim_resolver import resolve_input_status

        status = resolve_input_status(self.event)
        self.assertEqual(status["status"], "national_list_conditional")
        self.assertNotEqual(status["status"], "conventional_documented")
        # The label must still name the section and the restriction — softening it to a plain
        # allowance would be the opposite error.
        self.assertIn("205.602", status["label"])
        self.assertIn("Restricted", status["label"])

    def test_the_lot_level_organic_claim_survives_a_conditional_listing(self):
        """The blocker. A conditional match must not revoke the lot's organic claim.

        `resolve_lot_organic_eligibility` publishes "this lot: not represented as organic" on
        the consumer page when it fails. Firing that over a compliant calcium programme
        accuses a certified operation, in public, of something it did not do.
        """
        from datetime import date

        from history.services.claim_resolver import resolve_lot_organic_eligibility

        class _Cert:
            effective_date = date(2000, 1, 1)
            expiry_date = date(2099, 1, 1)
            scope = "crops"
            certification_scope = "crops"

        result = resolve_lot_organic_eligibility(self.history, _Cert())
        self.assertNotEqual(result.status, "prohibited_input")
        self.assertNotIn("Calcium chloride 33%", result.prohibited_inputs or [])

    def test_an_absolute_prohibition_still_revokes_the_lot(self):
        """The other half: the gate must keep working for real violations."""
        from datetime import date

        from history.services.claim_resolver import resolve_lot_organic_eligibility

        self.cacl.substance_name = "Glyphosate"
        self.cacl.cfr_section = "205.105"
        self.cacl.restriction_notes = "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."
        self.cacl.annotation_kind = NationalListSubstance.ANNOTATION_RATIONALE
        self.cacl.save()
        self.event.refresh_from_db()

        class _Cert:
            effective_date = date(2000, 1, 1)
            expiry_date = date(2099, 1, 1)
            scope = "crops"
            certification_scope = "crops"

        result = resolve_lot_organic_eligibility(self.history, _Cert())
        self.assertEqual(result.status, "prohibited_input")

    def test_the_evidence_aggregate_gets_its_own_tier(self):
        """Neither `contradicted` nor a silent promotion to plain grower_reported."""
        from history.transparency_views import _organic_input_evidence

        evidence = _organic_input_evidence([self.event])
        self.assertEqual(evidence["organic_input_evidence"]["conditional"], 1)
        self.assertEqual(evidence["organic_input_evidence"]["contradicted"], 0)
        self.assertEqual(evidence["organic_input_basis"], "conditional")
