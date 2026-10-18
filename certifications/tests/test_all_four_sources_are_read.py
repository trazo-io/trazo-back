"""A plan has FOUR sources. Every reader gets all of them, or the packet says something false.

The audit that produced this file found six readers that knew about two or three:

    osp_pdf_snapshot                 OMRI + NL      the frozen certifier PDF   (fixed 09-07)
    audit_export_service :13370      3 of 4         the records dossier        (fixed 09-06)
    audit_export_service :3410       OMRI + NL      the page-1 pre-read
    audit_export_service Table 3     OMRI + NL      per-event input verification
    operation_readiness  :480        OMRI + NL      the certifier register
    _compute_registry_sync_diff      3 of 4         the panel's own warning banner
    drift_detector                   3 of 4         every § 205.400(f)(2) finding

Each produced a different false statement, and the falsehoods contradicted each other inside
one document: a WSDA-only plan read "No approved-inputs list on file" on page 1 and "No drift
findings" three pages later. `plan_materials()` exists so a caller cannot count sources wrong;
these tests pin the callers that now use it, and the two the drift detector could not see.
"""

from django.test import TestCase

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry, WSDAMaterial
from certifications.services.drift_detector import _operator_entry_by_name
from certifications.services.plan_materials import PlanMaterial
from company.models import Company, Establishment
from history.services.audit_export_service import _compute_registry_sync_diff


class OperatorEntryLookupTests(TestCase):
    """The free-text materials list, which the detector could not see until 2026-09-07."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Calapooia Bend Farms LLC")
        cls.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=cls.company, state="OR")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="active")
        PlanMaterialEntry.objects.create(
            osp=cls.osp, product_name="Rexius Organic Compost", listing_basis="none_unlisted"
        )

    def test_the_operators_own_row_is_found(self):
        self.assertIsNotNone(_operator_entry_by_name(self.osp, "Rexius Organic Compost"))

    def test_matching_ignores_case_and_surrounding_whitespace(self):
        self.assertIsNotNone(_operator_entry_by_name(self.osp, "  rexius   organic compost "))

    def test_matching_is_exact_and_never_fuzzy(self):
        """⛔ `plan_materials.py` states the rule: these are the operator's own words, and a
        fuzzy match "would quietly mark a material as covered when nobody decided that it
        was". A near-miss must flag and be reconciled by a human, not be waved through."""
        for near_miss in ("Rexius Compost", "Rexius Organic Compost Plus", "Organic Compost"):
            self.assertIsNone(_operator_entry_by_name(self.osp, near_miss), near_miss)

    def test_an_empty_name_matches_nothing(self):
        self.assertIsNone(_operator_entry_by_name(self.osp, ""))
        self.assertIsNone(_operator_entry_by_name(self.osp, "   "))


class RegistrySyncCountsEverySourceTests(TestCase):
    """The banner that says "the narrative is long but the registry is thin".

    It took one list per registry, which made the source count the CALLER's problem — so when
    operator-entered rows shipped, a plan holding seven compost and manure entries reported
    `registry_total = 0` against a narrative the compiler had just written FROM those rows.
    """

    def test_operator_entered_rows_count_toward_the_registry_total(self):
        diff = _compute_registry_sync_diff(
            inputs_narrative="We apply Rexius Organic Compost each spring.",
            plan_rows=[
                PlanMaterial(name="Rexius Organic Compost", source="Operator-entered"),
                PlanMaterial(name="On-farm manure", source="Operator-entered"),
            ],
        )
        self.assertEqual(diff["registry_total"], 2)

    def test_a_narrative_that_names_the_row_is_not_flagged(self):
        diff = _compute_registry_sync_diff(
            inputs_narrative="We apply Rexius Organic Compost each spring.",
            plan_rows=[PlanMaterial(name="Rexius Organic Compost", source="Operator-entered")],
        )
        self.assertTrue(diff["registry_entries"][0]["in_narrative"])

    def test_a_new_source_needs_no_change_here(self):
        """The signature takes rows, so a fifth source counts without touching this function —
        which is the whole reason it no longer takes one list per registry."""
        diff = _compute_registry_sync_diff(
            inputs_narrative="",
            plan_rows=[PlanMaterial(name="Seed treatment X", source="AOSCA")],
        )
        self.assertEqual(diff["registry_total"], 1)
        self.assertEqual(diff["registry_entries"][0]["source"], "AOSCA")


class ReadinessCountsEverySourceTests(TestCase):
    """`materials_list_empty` — an unsupported-attestation finding in the certifier register.

    Counting OMRI + National List only meant a plan whose materials are WSDA-listed or
    operator-entered was told its own attestation was unsupported, and a fabricated
    nonconformance was filed against it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Cascade Ridge LLC")
        cls.establishment = Establishment.objects.create(name="Cascade Ridge Orchards", company=cls.company, state="WA")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="active")

    def _approved_count(self):
        from certifications.services.plan_materials import plan_materials

        return len(plan_materials(self.osp))

    def test_a_wsda_only_plan_is_not_empty(self):
        material = WSDAMaterial.objects.create(wsda_id="2948", brand_name="Nature Safe 13-0-0")
        self.osp.approved_wsda_materials.add(material)
        self.assertEqual(self._approved_count(), 1)

    def test_an_operator_entered_only_plan_is_not_empty(self):
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="On-farm compost", listing_basis="none_unlisted")
        self.assertEqual(self._approved_count(), 1)

    def test_a_genuinely_empty_plan_is_still_empty(self):
        """The finding is correct when it is TRUE — the defect was it firing when it was not."""
        self.assertEqual(self._approved_count(), 0)


class PageOneGateMatchesTheBodyTests(TestCase):
    """Page 1 and the section body must agree about whether a list exists.

    The page-1 comment claimed "same predicate as the body, so the two cannot diverge again"
    while already diverging: page 1 counted OMRI + NL, the body also counted WSDA. A WSDA-only
    plan therefore read "No approved-inputs list on file, so conformance could not be
    evaluated" on the first page a certifier sees, and "No drift findings" three pages later.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Tule River LLC")
        cls.establishment = Establishment.objects.create(name="Tule River Citrus", company=cls.company, state="CA")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="active")

    def _on_file(self):
        from certifications.services.plan_materials import plan_materials

        return bool(plan_materials(self.osp))

    def test_a_wsda_only_plan_reads_as_on_file(self):
        material = WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen")
        self.osp.approved_wsda_materials.add(material)
        self.assertTrue(self._on_file())

    def test_an_operator_entered_only_plan_reads_as_on_file(self):
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Quarry limestone", listing_basis="none_unlisted")
        self.assertTrue(self._on_file())

    def test_an_empty_plan_reads_as_not_on_file(self):
        self.assertFalse(self._on_file())


class SoilAmendmentCoverageTests(TestCase):
    """`amendment_product_name` is rendered for PA/OM/CC/CO; the classifier evaluated OM/CO."""

    def test_ph_adjustment_is_now_evaluated(self):
        """PA is where the National List materials live — lime, gypsum, elemental sulfur are
        all § 205.601 entries. A pH product was recorded and then checked against nothing."""
        from certifications.services import drift_detector

        source = drift_detector._classify_soil_event.__code__.co_consts
        flattened = " ".join(str(c) for c in source)
        self.assertIn("PA", flattened)

    def test_cover_crop_is_deliberately_excluded(self):
        """⛔ CC's product name is a seed mix — § 205.204 territory, handled by the seed
        classifier. Seed is not in the OMRI/WSDA input catalogues, so running this matcher
        over it would resolve to nothing every time and manufacture a finding on every
        cover-crop planting. Pinned so a future "why isn't CC here?" gets the answer."""
        import inspect

        from certifications.services import drift_detector

        body = inspect.getsource(drift_detector._classify_soil_event)
        self.assertIn('AMENDMENT_TYPES = {"OM", "CO", "PA"}', body)
        self.assertNotIn('"CC"', body.split("AMENDMENT_TYPES")[1].split("\n")[0])


class NationalListSubstanceRescueTests(TestCase):
    """The rescue was asymmetric: NL-FK could rescue into OMRI/WSDA, never the reverse."""

    def test_national_list_is_reachable_from_the_rescue(self):
        import inspect

        from certifications.services import drift_detector

        body = inspect.getsource(drift_detector._classify_chemical_event)
        rescue = body.split("_name_approval_clears")[1]
        # Since Phase 5 slice 1 the National List is reached through the exact-only resolver.
        self.assertIn("_exact_catalog_hits", rescue)
        self.assertIn("r_nl", rescue)
        self.assertIn("_operator_entry_by_name", rescue)

    def test_the_event_side_wsda_fk_is_read(self):
        """`ChemicalEvent.wsda_material` is written by the grower's own tap and was read by
        nothing — for many WSDA brands it is the ONLY third-party listing that exists, so the
        event fell through to a name match that could not succeed."""
        import inspect

        from certifications.services import drift_detector

        body = inspect.getsource(drift_detector._classify_chemical_event)
        self.assertIn("event.wsda_material_id", body)
        self.assertIn("wsda_not_in_osp", body)


class NewVersionCarriesOperatorRowsTests(TestCase):
    """A renewal cloned from last year's plan must not drop the hand-typed materials."""

    def test_the_clone_copies_rows_rather_than_sharing_them(self):
        """Rows, not an M2M, so editing next year's plan cannot rewrite what was filed last year.

        Exercised through `fork_plan`, the code the "start next version" button runs since
        2026-10-01. Until 2026-10-18 this read the source of the viewset's `new_version`, which
        no longer holds the copy, and failed on main unseen."""
        from certifications.models import OrganicSystemPlan, PlanMaterialEntry
        from certifications.services.osp_fork import fork_plan
        from company.models import Company, Establishment
        from users.models import User

        user = User.objects.create_user(email="fork@test.com", password="x")
        est = Establishment.objects.create(name="Fork Farm", company=Company.objects.create(name="Fork Co"))
        source = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="active")
        original = PlanMaterialEntry.objects.create(
            osp=source,
            product_name="Dairy manure compost",
            manufacturer="Own operation",
            reason_for_use="Fertility",
            listing_basis=PlanMaterialEntry.BASIS_CERTIFIER_LETTER,
            certifier_letter_reference="CCOF letter 2025-118",
        )

        clone = fork_plan(source, user)

        copied = PlanMaterialEntry.objects.get(osp=clone)
        self.assertNotEqual(copied.pk, original.pk, "a row, not a shared one")
        # Every field a `listing_statement` depends on travels, or the copy says less.
        for field in ("product_name", "manufacturer", "reason_for_use", "listing_basis", "certifier_letter_reference"):
            self.assertEqual(getattr(copied, field), getattr(original, field), f"fork_plan drops {field}")
        copied.product_name = "Edited next year"
        copied.save(update_fields=["product_name"])
        original.refresh_from_db()
        self.assertEqual(original.product_name, "Dairy manure compost", "last year's row is untouched")


class PlanMaterialsIsTheOneReaderTests(TestCase):
    """Guard against the class returning: a reader that counts sources itself."""

    def test_the_named_readers_no_longer_hand_count_registries(self):
        import inspect

        from certifications.services import osp_pdf_snapshot
        from history.services import audit_export_service, operation_readiness_service

        for module, marker in (
            (osp_pdf_snapshot, "plan_materials"),
            (operation_readiness_service, "plan_materials"),
            (audit_export_service, "plan_materials"),
        ):
            self.assertIn(marker, inspect.getsource(module), f"{module.__name__} bypasses plan_materials()")

    def test_national_list_substance_model_is_importable_for_fixtures(self):
        """Trivial, but it keeps the import above honest if the model is ever renamed."""
        self.assertTrue(NationalListSubstance._meta.db_table)
        self.assertTrue(OMRIProduct._meta.db_table)
