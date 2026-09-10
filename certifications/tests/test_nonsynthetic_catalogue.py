"""Nonsynthetic catalogue rows: re-filed off § 205.601 in place, and never spoken as a listing.

🔴 2026-09-10 — an eCFR check found three seeded § 205.601(e) rows that are not in § 205.601:
Spinosad, Microbial products (Bacillus thuringiensis) and d-Limonene. § 205.601 lists SYNTHETICS;
these are nonsynthetic, allowed unless § 205.602 names them (§ 205.105(b)). Every surface that
printed the section told a certifier — and the buyer page told a shopper — that the product was
a listed synthetic. Pinned here: the move keeps every plan and record attached, the classifier
still reaches the rows, and no certifier or consumer surface cites a section for them.
"""

import importlib
from datetime import date

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from certifications.management.commands.seed_national_list import (
    NONSYNTHETIC_RATIONALE,
    SECTION_601_ALLOWED,
    SECTION_NONSYN_ALLOWED,
    _normalize,
)
from certifications.models import NationalListSubstance, OrganicSystemPlan, PlanMaterialEntry
from certifications.serializers import _ApprovedNationalListInline
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import NONSYNTHETIC_SOURCE, plan_materials
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, Product

from .test_renewal_packet_contents import _pdf_text

MIGRATION = "certifications.migrations.0040_nonsynthetic_catalogue_rows"
NONSYN = NationalListSubstance.NONSYNTHETIC
SPINOSAD = "Spinosad"
BT = "Microbial products (Bacillus thuringiensis, etc.)"


def _row(name, section="205.601", **extra):
    return NationalListSubstance.objects.create(
        substance_name=name,
        substance_name_normalized=_normalize(name),
        cfr_section=section,
        subsection="e" if section == "205.601" else None,
        category="insecticide",
        status="allowed",
        **extra,
    )


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Tule River Citrus LLC")
        self.est = Establishment.objects.create(name="Tule River Citrus", company=company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.season = History.objects.create(
            name="Navels 2026",
            parcel=parcel,
            product=Product.objects.create(name="Oranges"),
            start_date=date(2026, 1, 10),
        )

    def _event(self, name, substance=None):
        event = ChemicalEvent.objects.create(
            history=self.season, type="PE", date=date(2026, 5, 1), commercial_name=name
        )
        ChemicalEvent.objects.filter(pk=event.pk).update(national_list_substance=substance)
        event.refresh_from_db()
        return event


class TheMigrationRefilesInPlaceTests(_Farm):
    def _refile(self):
        importlib.import_module(MIGRATION).refile(apps, None)

    def test_rows_keep_their_keys_plans_and_records(self):
        spinosad = _row(SPINOSAD, restriction_notes="Restricted to 3 applications/year per EPA label.")
        bt = _row(BT, restriction_notes="Nontoxigenic strains only.")
        self.osp.approved_national_list_substances.add(spinosad, bt)
        event = self._event("Entrust SC", spinosad)
        entry = PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Entrust SC", category="pest_disease_weed", national_list_substance=spinosad
        )
        before = NationalListSubstance.objects.count()

        self._refile()

        spinosad.refresh_from_db()
        self.assertEqual(
            (spinosad.cfr_section, spinosad.subsection, spinosad.restriction_notes, spinosad.annotation_kind),
            (NONSYN, None, NONSYNTHETIC_RATIONALE, NationalListSubstance.ANNOTATION_RATIONALE),
        )
        bt.refresh_from_db()
        self.assertEqual(bt.cfr_section, NONSYN)
        self.assertEqual(NationalListSubstance.objects.count(), before, "the move creates and deletes nothing")
        self.assertEqual(
            set(self.osp.approved_national_list_substances.values_list("pk", flat=True)), {spinosad.pk, bt.pk}
        )
        event.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(event.national_list_substance_id, spinosad.pk)
        self.assertEqual(entry.national_list_substance_id, spinosad.pk)

    def test_a_real_601_row_is_untouched(self):
        lime = _row("Lime sulfur", restriction_notes="Including calcium polysulfide.")
        self._refile()
        lime.refresh_from_db()
        self.assertEqual((lime.cfr_section, lime.subsection), ("205.601", "e"))

    def test_an_existing_nonsynthetic_row_leaves_the_601_row_for_review(self):
        listed = _row(SPINOSAD)
        _row(SPINOSAD, section=NONSYN)
        self._refile()
        listed.refresh_from_db()
        self.assertEqual(listed.cfr_section, "205.601")
        self.assertEqual(NationalListSubstance.objects.filter(substance_name=SPINOSAD).count(), 2)

    def test_the_migration_and_the_seeder_agree(self):
        migration = importlib.import_module(MIGRATION)
        self.assertEqual(set(migration.ROWS), {_normalize(name) for _c, name, _n in SECTION_NONSYN_ALLOWED})
        self.assertEqual(migration.NOTE, NONSYNTHETIC_RATIONALE)
        still_at_601 = {_normalize(name) for _s, _c, name, _n in SECTION_601_ALLOWED} & set(migration.ROWS)
        self.assertEqual(still_at_601, set())


class TheSeederAndTheClassifierTests(_Farm):
    def setUp(self):
        super().setUp()
        call_command("seed_national_list", verbosity=0)

    def test_a_seed_writes_them_as_nonsynthetic_and_never_at_601(self):
        for _category, name, _notes in SECTION_NONSYN_ALLOWED:
            self.assertTrue(NationalListSubstance.objects.filter(substance_name=name, cfr_section=NONSYN).exists())
            self.assertFalse(NationalListSubstance.objects.filter(substance_name=name, cfr_section="205.601").exists())

    def test_brands_and_shorthand_still_reach_the_rows(self):
        from history.signals import auto_classify_chemical_against_national_list

        for text, expected in (("Entrust SC (Spinosad 22.5%)", SPINOSAD), ("Bt", BT)):
            event = ChemicalEvent(commercial_name=text)
            auto_classify_chemical_against_national_list(sender=ChemicalEvent, instance=event)
            self.assertIsNotNone(event.national_list_substance, text)
            self.assertEqual(
                (event.national_list_substance.substance_name, event.national_list_substance.cfr_section),
                (expected, NONSYN),
            )


class NoSurfaceCitesASectionForThemTests(_Farm):
    def setUp(self):
        super().setUp()
        self.spinosad = _row(
            SPINOSAD,
            section=NONSYN,
            restriction_notes=NONSYNTHETIC_RATIONALE,
            annotation_kind=NationalListSubstance.ANNOTATION_RATIONALE,
        )

    def test_the_row_has_no_citation(self):
        self.assertFalse(self.spinosad.is_national_list_entry)
        self.assertEqual(self.spinosad.citation, "")
        self.assertIn("no National List entry", str(self.spinosad))
        self.assertEqual(_row("Elemental sulfur").citation, "§ 205.601(e)")

    def test_the_plan_files_it_under_its_own_heading(self):
        self.osp.approved_national_list_substances.add(self.spinosad)
        row = next(r for r in plan_materials(self.osp) if r.name == SPINOSAD)
        self.assertEqual((row.source, row.identifier), (NONSYNTHETIC_SOURCE, ""))
        self.assertNotIn("205.601", row.display(stated_absences=True))

    def test_the_materials_page_cites_no_section(self):
        self.osp.approved_national_list_substances.add(self.spinosad)
        page = " ".join(_pdf_text(generate_module_pdf(self.osp, "materials_application")).split())
        # The page header lists the module's own citations (§ 205.601 among them); the row is what
        # must cite nothing, filed under a heading that says it is not a listing.
        self.assertIn("Nonsynthetic, no National List entry", page)
        line = page[page.index(SPINOSAD) :].split("Definition version", 1)[0]
        self.assertNotIn("205.601", line)

    def test_the_verifier_does_not_verify_it(self):
        from certifications.services.omri_verifier import OMRIProductVerifier

        result = OMRIProductVerifier().verify(operation_name=SPINOSAD)
        self.assertFalse(result.found)
        self.assertEqual(result.status, "not_found")
        self.assertNotIn("7 CFR", result.certifier_name or "")
        self.assertIn("nonsynthetic", result.notes)

    def test_the_api_hands_the_client_an_empty_citation(self):
        self.assertEqual(_ApprovedNationalListInline(self.spinosad).data["citation"], "")
        self.assertFalse(_ApprovedNationalListInline(self.spinosad).data["is_national_list_entry"])
        self.assertTrue(_ApprovedNationalListInline(_row("Elemental sulfur")).data["is_national_list_entry"])

    def test_the_buyer_page_claims_no_listing(self):
        """⛔ Consumer claim safety. "Allowed input · National List § 205.601" for spinosad was a
        regulatory citation that does not exist, published to shoppers."""
        from history.services.claim_authority import (
            LABEL_INPUT_NATIONAL_LIST,
            LABEL_INPUT_UNCLASSIFIED,
            may_claim_input_listing,
        )
        from history.services.claim_resolver import resolve_input_status

        event = self._event("Entrust SC", self.spinosad)
        decision = may_claim_input_listing(event)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.safe_label, LABEL_INPUT_UNCLASSIFIED)
        chip = resolve_input_status(event)
        self.assertNotEqual(chip["status"], "national_list_allowed")
        self.assertNotIn("National List", chip["label"])

        control = self._event("Elemental sulfur 90", _row("Elemental sulfur"))
        self.assertEqual(may_claim_input_listing(control).safe_label, LABEL_INPUT_NATIONAL_LIST)
