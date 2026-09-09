"""Parcel model behaviour — the accessors the consumer and carbon surfaces read.

REWRITTEN 2026-08-20. The previous file was aspirational: it tested a `Parcel` with `city`,
`state`, `latitude`, `longitude`, `irrigation_type`, `organic_certified` and `created_by`
(none of which the model has), and it defined its own fake `CropTemplate` and
`ProductCertification` classes whose "manager" built an object out of whatever kwargs the
test passed. Those two suites therefore asserted that a dict contains what the test had just
put in it — they could not fail, no matter what the product did. The rest raised
`TypeError: Parcel() got unexpected keyword arguments` on setUp.

33 of its 38 tests errored and the remaining 5 proved nothing, so the file read as coverage
while providing none. Replaced with tests against the model as it actually is.

Scope is deliberately narrow: parcel area units live in `test_parcel_area_units.py`, the area
floor in `test_parcel_area_floor.py`, buffers in `test_buffer_zones.py`, the § 205.202 wizard
in `test_parcel_application.py`, and season targeting in `test_finish_targets_named_season.py`.
What had NO coverage anywhere — and is what this file now covers — are the eight
`agricultural_details` accessors that the consumer QR page and the carbon readiness surfaces
read on every request.
"""

from django.db.models import Avg, Count, Sum
from django.test import TestCase

from company.models import Company, Establishment
from product.models import Parcel, Product


class ParcelTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Ridgeline Growers")
        cls.establishment = Establishment.objects.create(name="Ridge Farm", company=cls.company)

    def parcel(self, **kwargs):
        kwargs.setdefault("name", "Ridge Block")
        kwargs.setdefault("establishment", self.establishment)
        kwargs.setdefault("area", 11.4931)
        return Parcel.objects.create(**kwargs)


class ParcelCoreTests(ParcelTestBase):
    """The fields a parcel cannot exist without, and the ones it can."""

    def test_a_parcel_needs_only_a_name_an_establishment_and_an_area(self):
        parcel = self.parcel()
        self.assertEqual(parcel.name, "Ridge Block")
        self.assertEqual(parcel.establishment, self.establishment)
        self.assertEqual(parcel.area, 11.4931)

    def test_optional_fields_default_to_empty_rather_than_none(self):
        """`agricultural_details` must be a dict on a fresh row.

        Every accessor below calls `.get()` on it directly, with no guard, so a `None`
        default would turn the consumer QR page into an AttributeError for any parcel the
        farmer had not filled in.
        """
        parcel = self.parcel()
        self.assertEqual(parcel.agricultural_details, {})
        self.assertEqual(parcel.application_answers, {})
        self.assertFalse(parcel.certified)
        self.assertFalse(parcel.container_production)

    def test_str_identifies_the_parcel_and_its_farm(self):
        parcel = self.parcel(name="Creek Block")
        self.assertIn("Creek Block", str(parcel))
        self.assertIn("Ridge Farm", str(parcel))

    def test_a_parcel_may_carry_a_product(self):
        product = Product.objects.create(name="Apples")
        parcel = self.parcel(product=product)
        parcel.refresh_from_db()
        self.assertEqual(parcel.product, product)


class ParcelAgriculturalDetailTests(ParcelTestBase):
    """The `agricultural_details` accessors, including the aliases they tolerate.

    Each of these reads more than one key because the parcel form has changed field names
    over time and older rows still hold the old ones. That fallback chain is the behaviour
    worth pinning: drop a key from it and historic parcels silently go blank on the consumer
    page rather than erroring anywhere a deploy would catch.
    """

    def test_primary_crop_falls_back_to_the_older_key(self):
        self.assertEqual(
            self.parcel(agricultural_details={"primary_crop": "Honeycrisp"}).get_primary_crop(), "Honeycrisp"
        )
        self.assertEqual(self.parcel(agricultural_details={"crop_focus": "Gala"}).get_primary_crop(), "Gala")

    def test_primary_crop_prefers_the_current_key_when_both_are_present(self):
        parcel = self.parcel(agricultural_details={"primary_crop": "Honeycrisp", "crop_focus": "Gala"})
        self.assertEqual(parcel.get_primary_crop(), "Honeycrisp")

    def test_primary_crop_is_a_string_when_nothing_is_recorded(self):
        """Never None: callers concatenate this into consumer copy."""
        self.assertEqual(self.parcel().get_primary_crop(), "")

    def test_sustainability_practices_reads_three_keys_in_order(self):
        cases = [
            ({"sustainability_practices": "Permanent grass alleyway"}, "Permanent grass alleyway"),
            ({"cover_crop_management": "Resident winter cover"}, "Resident winter cover"),
            ({"carbon_sequestration_practices": "Compost banded in the tree row"}, "Compost banded in the tree row"),
            ({}, ""),
        ]
        for details, expected in cases:
            with self.subTest(details=details):
                self.assertEqual(self.parcel(agricultural_details=details).get_sustainability_practices(), expected)

    def test_transparency_description_is_the_parcel_description(self):
        self.assertEqual(
            self.parcel(description="Twenty-eight acres of Honeycrisp").get_transparency_description(),
            "Twenty-eight acres of Honeycrisp",
        )
        self.assertEqual(self.parcel().get_transparency_description(), "")

    def test_agricultural_detail_get_and_set_round_trip(self):
        parcel = self.parcel()
        parcel.set_agricultural_detail("soil_ph", 6.4)
        parcel.save(update_fields=["agricultural_details"])
        parcel.refresh_from_db()
        self.assertEqual(parcel.get_agricultural_detail("soil_ph"), 6.4)
        self.assertIsNone(parcel.get_agricultural_detail("missing_key"))
        self.assertEqual(parcel.get_agricultural_detail("missing_key", "fallback"), "fallback")


# `ParcelTransparencyScoreTests` and `ParcelTransparencyReadyTests` removed 2026-09-09 with
# the two methods they pinned. They were doing their job — the bands they held were exactly
# `get_transparency_score()`'s 40/30/20 arithmetic — but a test that pins a retired concept
# keeps it alive: the score is retired as a CONCEPT, so there are no bands left to protect.
#
# The replacement guard is `ParcelHasNoSelfGradeTests` below, which asserts the ABSENCE of both
# methods and of the two serializer fields, so the score cannot come back by re-adding a
# method that nothing currently reads.


class ParcelCarbonReadinessTests(ParcelTestBase):
    """Carbon-readiness completeness checks over `agricultural_details`."""

    def test_readiness_score_is_the_share_of_thirty_seven_fields_filled(self):
        parcel = self.parcel(agricultural_details={f"field_{i}": "value" for i in range(37)})
        self.assertEqual(parcel.calculate_carbon_readiness_score(), 100)

        half = self.parcel(agricultural_details={f"field_{i}": "value" for i in range(18)})
        self.assertAlmostEqual(half.calculate_carbon_readiness_score(), 18 / 37 * 100, places=4)

    def test_empty_values_do_not_count_toward_readiness(self):
        """A key present with a blank value is not a recorded fact.

        `calculate_carbon_readiness_score` filters on truthiness, which is the right call and
        the opposite of what `has_complete_soil_data` does — see the test below.
        """
        parcel = self.parcel(agricultural_details={"soil_ph": "", "soil_nitrogen": None, "cover_crop": "rye"})
        self.assertAlmostEqual(parcel.calculate_carbon_readiness_score(), 1 / 37 * 100, places=4)

    def test_readiness_score_is_capped_at_one_hundred(self):
        parcel = self.parcel(agricultural_details={f"field_{i}": "value" for i in range(80)})
        self.assertEqual(parcel.calculate_carbon_readiness_score(), 100)

    def test_soil_completeness_needs_all_five_fields(self):
        soil = {"soil_ph": 6.4, "soil_organic_matter": 2.8, "soil_nitrogen": 12, "soil_phosphorus": 30}
        self.assertFalse(self.parcel(agricultural_details=soil).has_complete_soil_data())
        self.assertTrue(self.parcel(agricultural_details={**soil, "soil_potassium": 180}).has_complete_soil_data())

    def test_soil_completeness_counts_a_blank_value_as_complete(self):
        """⚠️ Documented weakness, not an endorsement.

        `has_complete_soil_data` tests `field in self.agricultural_details` — presence of the
        KEY — while `update_usda_compliance_status` on the same model tests presence AND
        truthiness. So a parcel whose form was opened and saved without values reports
        complete soil data to anything that asks.

        Pinned rather than fixed because the method currently has NO callers in production
        code (checked 2026-08-20; grep usage, not definition). Wire it up and this becomes a
        real bug — it is the "blank is not a value" class that has already bitten the carbon
        activity sweep. The assertion below is what it does today, so a fix will fail here
        loudly and deliberately.
        """
        blank = dict.fromkeys(
            ["soil_ph", "soil_organic_matter", "soil_nitrogen", "soil_phosphorus", "soil_potassium"], ""
        )
        self.assertTrue(self.parcel(agricultural_details=blank).has_complete_soil_data())

    def test_conservation_completeness_needs_all_four_fields(self):
        conservation = {
            "cover_crop_management": "Resident winter cover",
            "crop_rotation_pattern": "Perennial",
            "carbon_sequestration_practices": "Compost",
        }
        self.assertFalse(self.parcel(agricultural_details=conservation).has_complete_conservation_data())
        complete = {**conservation, "integrated_pest_management": "Mating disruption"}
        self.assertTrue(self.parcel(agricultural_details=complete).has_complete_conservation_data())

    def test_usda_compliance_requires_every_field_to_be_non_empty(self):
        """The contrast case: this one is written correctly."""
        fields = {
            "soil_organic_matter": 2.8,
            "nrcs_practices": "EQIP",
            "organic_certification_status": "certified",
            "cover_crop_management": "Resident winter cover",
            "irrigation_efficiency": 0.85,
        }
        parcel = self.parcel(agricultural_details=fields)
        parcel.update_usda_compliance_status()
        self.assertTrue(parcel.usda_compliance_eligible)

        blanked = self.parcel(agricultural_details={**fields, "nrcs_practices": ""})
        blanked.update_usda_compliance_status()
        self.assertFalse(blanked.usda_compliance_eligible)


class ParcelAggregationTests(ParcelTestBase):
    """The aggregate queries the farm dashboard and the certifier dossier both run.

    The dossier reconciles a farm's stated acreage against the sum of its parcels, so these
    aggregates are load-bearing rather than decorative.
    """

    def setUp(self):
        self.parcel(name="Ridge Block", area=11.4931, certified=True, soil_type="clay_loam")
        self.parcel(name="Creek Block", area=6.7987, certified=True, soil_type="clay_loam")
        self.parcel(name="Bench Block", area=5.7465, certified=False, soil_type="sandy_loam")

    def test_total_area_sums_across_parcels(self):
        total = Parcel.objects.filter(establishment=self.establishment).aggregate(total=Sum("area"))["total"]
        self.assertAlmostEqual(total, 24.0383, places=4)

    def test_total_area_in_acres_matches_the_per_parcel_conversion(self):
        """The dossier prints acres; the column is stored in hectares."""
        parcels = Parcel.objects.filter(establishment=self.establishment)
        self.assertAlmostEqual(sum(p.area_acres for p in parcels), 59.4, places=1)

    def test_soil_type_distribution(self):
        counts = {
            row["soil_type"]: row["n"]
            for row in Parcel.objects.filter(establishment=self.establishment)
            .values("soil_type")
            .annotate(n=Count("id"))
        }
        self.assertEqual(counts, {"clay_loam": 2, "sandy_loam": 1})

    def test_certified_parcel_count(self):
        qs = Parcel.objects.filter(establishment=self.establishment)
        self.assertEqual(qs.filter(certified=True).count(), 2)
        self.assertEqual(qs.count(), 3)

    def test_average_parcel_area(self):
        avg = Parcel.objects.filter(establishment=self.establishment).aggregate(avg=Avg("area"))["avg"]
        self.assertAlmostEqual(avg, 24.0383 / 3, places=4)

    def test_aggregates_are_scoped_to_the_establishment(self):
        """A farm's totals must not pick up another company's parcels."""
        other_company = Company.objects.create(name="Unrelated Co")
        other_est = Establishment.objects.create(name="Unrelated Farm", company=other_company)
        Parcel.objects.create(name="Elsewhere", establishment=other_est, area=100.0)

        total = Parcel.objects.filter(establishment=self.establishment).aggregate(total=Sum("area"))["total"]
        self.assertAlmostEqual(total, 24.0383, places=4)


class ParcelQueryEfficiencyTests(ParcelTestBase):
    """`select_related` on the establishment chain, which every parcel list renders."""

    def setUp(self):
        for i in range(10):
            self.parcel(name=f"Block {i}", area=1.0 + i)

    def test_listing_parcels_with_their_farm_takes_one_query(self):
        with self.assertNumQueries(1):
            rows = list(
                Parcel.objects.filter(establishment=self.establishment).select_related("establishment__company")
            )
            # Touch the far end of the join — without select_related this is 20 more queries.
            self.assertEqual({p.establishment.company.name for p in rows}, {"Ridgeline Growers"})

    def test_bulk_create_writes_every_parcel(self):
        Parcel.objects.bulk_create(
            [Parcel(name=f"Bulk {i}", establishment=self.establishment, area=2.0) for i in range(25)]
        )
        self.assertEqual(Parcel.objects.filter(establishment=self.establishment, name__startswith="Bulk").count(), 25)


class ParcelHasNoSelfGradeTests(ParcelTestBase):
    """A parcel does not grade itself — not as a number, and not as a verdict.

    Replaces `ParcelTransparencyScoreTests` / `ParcelTransparencyReadyTests`, removed
    2026-09-09 with the methods they pinned. `get_transparency_score()` was a 0-100 self-grade
    of the operation's own documentation (40 points for a 100-character description, 30 for any
    practices text, 20 for three photos) served on the authenticated parcel payload;
    `is_transparency_ready()` was the same arithmetic with the number filed off.

    This asserts the ABSENCE, because the failure mode is re-addition: the score is retired as
    a CONCEPT (.claude/rules/transparency-first.md), so a method with no current reader is
    still a regression the moment someone wires a serializer to it.
    """

    RETIRED_METHODS = ("get_transparency_score", "is_transparency_ready")
    RETIRED_SERIALIZER_FIELDS = ("transparency_score", "transparency_ready")

    def test_the_model_carries_no_self_grading_method(self):
        for name in self.RETIRED_METHODS:
            with self.subTest(method=name):
                self.assertFalse(
                    hasattr(Parcel, name),
                    f"Parcel.{name}() is a self-assigned grade over self-reported inputs. "
                    "A producer surface gets counts and a checklist naming the missing "
                    "document — never a total, a percentage or a verdict.",
                )

    def test_the_parcel_payload_carries_no_self_grade(self):
        """The serializer is the surface that actually printed it, so it is asserted directly."""
        from product.serializers import RetrieveParcelSerializer

        parcel = self.parcel(
            description="Twenty-eight acres of Honeycrisp on a two-wire trellis, planted 2014.",
            agricultural_details={"sustainability_practices": "Permanent grass alleyway"},
        )
        payload = RetrieveParcelSerializer(parcel).data

        for field in self.RETIRED_SERIALIZER_FIELDS:
            with self.subTest(field=field):
                self.assertNotIn(field, payload)

        # And the factual replacement is still there — otherwise this test would pass just as
        # well on a serializer that reports nothing about the parcel's § 205.202 readiness.
        self.assertIn("application_status", payload)
        self.assertIn("application_missing", payload)
