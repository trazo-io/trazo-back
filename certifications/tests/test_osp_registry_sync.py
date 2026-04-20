"""
OSP Registry Sync diff tests — P0-5 (2026-04-15).

Covers _compute_registry_sync_diff and its serializer projection:
- Empty narrative + empty registry → no warning (nothing to reconcile).
- Empty narrative + populated registry → all entries "not in narrative".
- Narrative mentions every registry entry → has_warning=False.
- Narrative misses one registry entry → that entry is in
  entries_not_in_narrative; has_warning=True.
- Narrative long but registry thin → has_warning=True (signal to fix filing).
- Normalizer collapses whitespace/hyphens so "Kocide-3000" matches
  narrative that says "Kocide 3000".
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.serializers import OrganicSystemPlanSerializer
from company.models import Company, Establishment
from history.services.audit_export_service import _compute_registry_sync_diff, _normalize_input_name


class RegistrySyncDiffHelperTests(TestCase):
    def test_normalizer_collapses_whitespace_and_punctuation(self):
        self.assertEqual(_normalize_input_name("Kocide 3000"), "kocide3000")
        self.assertEqual(_normalize_input_name("Kocide-3000"), "kocide3000")
        self.assertEqual(_normalize_input_name("  Neptune's Harvest "), "neptunesharvest")
        self.assertEqual(_normalize_input_name(None), "")
        self.assertEqual(_normalize_input_name(""), "")

    def test_empty_narrative_empty_registry_is_zero(self):
        diff = _compute_registry_sync_diff(inputs_narrative="", omri_products=[], wsda_materials=[], nl_substances=[])
        self.assertEqual(diff["registry_total"], 0)
        self.assertEqual(diff["registry_entries"], [])

    def test_narrative_mentions_every_entry_is_clean(self):
        omri = OMRIProduct.objects.create(omri_id="O1", product_name="Kocide 3000")
        wsda = WSDAMaterial.objects.create(wsda_id="W1", brand_name="Regalia Biofungicide", category="pesticide")
        nl = NationalListSubstance.objects.create(
            substance_name="Sulfur", substance_name_normalized="sulfur", cfr_section="205.601"
        )
        narrative = (
            "We use Kocide 3000 as a copper fungicide, Regalia Biofungicide "
            "for disease suppression, and Sulfur for mite control."
        )
        diff = _compute_registry_sync_diff(
            inputs_narrative=narrative,
            omri_products=[omri],
            wsda_materials=[wsda],
            nl_substances=[nl],
        )
        self.assertEqual(diff["registry_total"], 3)
        self.assertTrue(all(e["in_narrative"] for e in diff["registry_entries"]))

    def test_narrative_missing_entry_is_flagged(self):
        omri = OMRIProduct.objects.create(omri_id="O2", product_name="Kocide 3000")
        wsda = WSDAMaterial.objects.create(wsda_id="W2", brand_name="Regalia Biofungicide", category="pesticide")
        narrative = "We use Kocide 3000 as a copper fungicide."
        diff = _compute_registry_sync_diff(
            inputs_narrative=narrative,
            omri_products=[omri],
            wsda_materials=[wsda],
            nl_substances=[],
        )
        self.assertEqual(diff["registry_total"], 2)
        kocide_entry = next(e for e in diff["registry_entries"] if e["source"] == "OMRI")
        regalia_entry = next(e for e in diff["registry_entries"] if e["source"] == "WSDA")
        self.assertTrue(kocide_entry["in_narrative"])
        self.assertFalse(regalia_entry["in_narrative"])

    def test_hyphenated_variant_still_matches(self):
        omri = OMRIProduct.objects.create(omri_id="O3", product_name="Kocide 3000")
        narrative = "Applied Kocide-3000 at recommended rate."
        diff = _compute_registry_sync_diff(
            inputs_narrative=narrative,
            omri_products=[omri],
            wsda_materials=[],
            nl_substances=[],
        )
        self.assertTrue(diff["registry_entries"][0]["in_narrative"])


class OrganicSystemPlanSerializerSyncDiffTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Sync Farm")
        self.establishment = Establishment.objects.create(name="E1", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def test_no_warning_when_narrative_and_registry_empty(self):
        data = OrganicSystemPlanSerializer(self.osp).data
        diff = data["registry_sync_diff"]
        self.assertFalse(diff["has_warning"])
        self.assertEqual(diff["registry_total"], 0)

    def test_warning_when_registry_entry_not_in_narrative(self):
        omri = OMRIProduct.objects.create(omri_id="O9", product_name="Kocide 3000")
        self.osp.approved_omri_products.add(omri)
        # Narrative doesn't mention Kocide.
        self.osp.sections = {
            **(self.osp.sections or {}),
            "inputs_list": {"narrative": "We rely on cover crops and compost.", "last_updated": None},
        }
        self.osp.save()
        data = OrganicSystemPlanSerializer(self.osp).data
        diff = data["registry_sync_diff"]
        self.assertTrue(diff["has_warning"])
        self.assertEqual(len(diff["entries_not_in_narrative"]), 1)
        self.assertEqual(diff["entries_not_in_narrative"][0]["name"], "Kocide 3000")

    def test_warning_when_long_narrative_but_thin_registry(self):
        # Narrative >= 400 chars but zero registered inputs → has_warning=True
        # via the second condition (narrative ≥ 400 chars, registry < 3).
        long_narrative = (
            "We use a comprehensive integrated pest management program combining "
            "beneficial insects, cover cropping, and organic-approved fungicides "
            "applied when monitoring indicates pressure exceeds thresholds. Our "
            "approved inputs include copper hydroxide, sulfur dust, and Regalia "
            "biofungicide for disease suppression; fish emulsion and composted "
            "dairy manure for fertility; and pheromone traps for ongoing "
            "population monitoring throughout the growing season."
        )
        self.assertGreaterEqual(len(long_narrative), 400)
        self.osp.sections = {
            **(self.osp.sections or {}),
            "inputs_list": {"narrative": long_narrative, "last_updated": None},
        }
        self.osp.save()
        data = OrganicSystemPlanSerializer(self.osp).data
        diff = data["registry_sync_diff"]
        self.assertTrue(diff["has_warning"])
        self.assertEqual(diff["registry_total"], 0)
        self.assertEqual(diff["entries_not_in_narrative"], [])
        self.assertGreaterEqual(diff["narrative_char_count"], 400)
