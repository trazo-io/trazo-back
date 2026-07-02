"""
End-to-end integration test — Sprint 3.

Proves that saving a ChemicalEvent without an explicit `national_list_substance`
triggers the auto-classification signal and populates the FK. This is the
integration point the user can exercise today WITHOUT any frontend changes:
just save a chemical event and it gets classified.
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, Product
from users.models import User


class ChemicalEventAutoClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            category="disease_control",
            status="allowed",
            restriction_notes="Minimize soil accumulation.",
        )
        NationalListSubstance.objects.create(
            substance_name="Rotenone",
            substance_name_normalized="rotenone",
            cfr_section="205.602",
            status="prohibited",
        )

    def setUp(self):
        self.user = User.objects.create_user(email="c@test.com", password="x")
        self.company = Company.objects.create(name="Test Farm")
        self.establishment = Establishment.objects.create(name="Field", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.product = Product.objects.create(name="Tomato")
        self.history = History.objects.create(
            name="H",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_exact_name_auto_classifies_on_save(self):
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied copper hydroxide",
            date=timezone.now(),
            chemical_subtype="copper_fungicide",
            commercial_name="Copper hydroxide",
        )
        self.assertIsNotNone(event.national_list_substance)
        self.assertEqual(event.national_list_substance.cfr_section, "205.601")
        self.assertEqual(event.national_list_substance.status, "allowed")

    def test_contained_name_auto_classifies_on_save(self):
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied copper hydroxide",
            date=timezone.now(),
            chemical_subtype="copper_fungicide",
            commercial_name="Copper Hydroxide 25% WP",
        )
        self.assertIsNotNone(event.national_list_substance)
        self.assertEqual(event.national_list_substance.substance_name, "Copper hydroxide")

    def test_prohibited_substance_auto_classifies(self):
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied rotenone",
            date=timezone.now(),
            chemical_subtype="organic_pesticide",
            commercial_name="Rotenone",
        )
        self.assertIsNotNone(event.national_list_substance)
        self.assertEqual(event.national_list_substance.status, "prohibited")

    def test_unknown_substance_leaves_fk_null(self):
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied mystery product",
            date=timezone.now(),
            chemical_subtype="synthetic_pesticide",
            commercial_name="TotallyMadeUpBrand",
        )
        self.assertIsNone(event.national_list_substance)

    def test_explicit_fk_is_not_overwritten(self):
        # If admin/CLI sets the FK explicitly, the signal must respect that.
        rotenone = NationalListSubstance.objects.get(substance_name_normalized="rotenone")
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied copper hydroxide (manually classified as something else)",
            date=timezone.now(),
            chemical_subtype="copper_fungicide",
            commercial_name="Copper hydroxide",
            national_list_substance=rotenone,
        )
        # Should still be rotenone, not auto-reclassified to copper hydroxide.
        self.assertEqual(event.national_list_substance, rotenone)

    def test_nop_5034_2_prohibited_synthetic_auto_classifies(self):
        # NOP 5034-2 Appendix: a common prohibited synthetic (glyphosate) seeded
        # under § 205.105 must classify as prohibited so the audit export fires
        # the hard-disqualification path instead of leaving it "unresolved".
        NationalListSubstance.objects.create(
            substance_name="Glyphosate",
            substance_name_normalized="glyphosate",
            cfr_section="205.105",
            subsection="a",
            category="herbicide",
            status="prohibited",
            restriction_notes="Synthetic herbicide; not on § 205.601 (NOP 5034-2).",
        )
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied glyphosate",
            date=timezone.now(),
            chemical_subtype="synthetic_pesticide",
            commercial_name="Glyphosate",
        )
        self.assertIsNotNone(event.national_list_substance)
        self.assertEqual(event.national_list_substance.status, "prohibited")
        self.assertEqual(event.national_list_substance.cfr_section, "205.105")

    def test_false_positive_guard_on_generic_word(self):
        # Farmer applies sodium hydroxide (prohibited conventional, NOT on allowed list).
        # Signal must NOT falsely classify it as "Copper hydroxide".
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Applied sodium hydroxide",
            date=timezone.now(),
            chemical_subtype="synthetic_fertilizer",
            commercial_name="Sodium hydroxide",
        )
        self.assertIsNone(event.national_list_substance)
