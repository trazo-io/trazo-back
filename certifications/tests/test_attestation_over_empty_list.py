"""
Class A guard: an attestation cannot be affirmed over an empty list.

The defect, found on the pilot farm 2026-08-27 and reproduced live: G8.0 reported
"Completed · 3 of 3 required" while its generated PDF printed

    No record types have been confirmed in the Common OSP § 11 registry yet.
    Do you maintain the records confirmed above, keep them for at least 5 years, and make them
    available at inspection?  Yes

CCOF's G8.0 section A *is* that list, so the module a certifier opens first was a signature over
nothing. Cause: the § 11 registry is an `info` embed, and `info` is skipped by completion
validation, so the module's three radios were the whole bar.

Tested at three levels because a gate in one place is not a gate:
  * the rule itself (`blocked_attestations`);
  * the API write path — the untrue value must never reach storage, since the compiler reads
    stored answers straight into the § 205.201(a) narrative;
  * the generated PDF, for plans attested before the gate existed.

Plus the deliberate exclusion: the materials-list attestation is NOT gated this way, because an
operation that applies nothing has an empty list and the attestation is then vacuously true.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.common_osp_records import confirm
from company.models import Company, Establishment
from users.models import User, WorksIn

G8 = "g8_0_record_keeping"
ATTESTATION = "records_retention_attestation"


def _answer_activities(osp):
    """Answer every question that decides a required record type (`required_records.TRIGGERS`), so
    the only requirement left is harvest records: this plan names who harvests, and nothing else.

    Since 2026-10-01 (OSP alignment audit T17-F1) one confirmed record no longer opens the gate on
    its own: every record type the plan's answers require must be confirmed, and an unanswered
    deciding question keeps the gate shut.
    """
    modules = dict((osp.module_responses or {}).get("modules") or {})

    def answer(module, **values):
        entry = dict(modules.get(module) or {})
        entry["answers"] = {**(entry.get("answers") or {}), **values}
        modules[module] = entry

    answer("materials_application", no_materials_used=True)
    answer("g5_0_pest", applies_pest_weed_disease_inputs=False)
    answer("g6_1_harvest_transport", who_harvests="own_crew")
    answer("g4_1_compost_manure", materials_applied=["purchased_compost"])
    answer("g6_2_storage", storage_shared_with_nonorganic=False)
    answer("g6_5_sales_soe", sales_soe_supplier_verification="no")
    answer("g3_0_seeds", seeds_used=["organic_untreated"])
    osp.module_responses = {**(osp.module_responses or {}), "modules": modules}
    osp.save(update_fields=["module_responses"])


class AttestationGateRuleTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.module = MODULES_BY_KEY[G8]

    def test_affirming_over_an_empty_registry_is_blocked(self):
        blocked = blocked_attestations(self.module, {ATTESTATION: True}, self.osp)
        self.assertIn(ATTESTATION, blocked)
        self.assertIn("Confirm at least one record type", blocked[ATTESTATION])

    def test_confirming_every_record_the_plan_requires_unblocks_it(self):
        """Was "one confirmation unblocks it". A single confirmed record now opens the gate only
        when it is the one record the plan's answers require (audit T17-F1)."""
        _answer_activities(self.osp)
        confirm(self.osp, ["harvest_records"], user=None)
        self.osp.refresh_from_db()
        self.assertEqual(blocked_attestations(self.module, {ATTESTATION: True}, self.osp), {})

    def test_a_negative_answer_is_never_blocked(self):
        # "No, I do not maintain these records" over an empty list is coherent — and it is the
        # honest answer a farm might give. Only the affirmative claims something.
        self.assertEqual(blocked_attestations(self.module, {ATTESTATION: False}, self.osp), {})

    def test_an_unanswered_attestation_is_not_blocked_here(self):
        # Required-field validation owns that case; this gate must not double-report it.
        self.assertEqual(blocked_attestations(self.module, {}, self.osp), {})

    def test_the_materials_attestation_is_deliberately_not_gated(self):
        # An operation that applies nothing has an empty materials list and the attestation is
        # vacuously TRUE. Gating it would force a no-spray grower to lie or stay incomplete.
        materials = MODULES_BY_KEY["materials_application"]
        self.assertEqual(blocked_attestations(materials, {"materials_list_complete": True}, self.osp), {})


class AttestationGateAPITests(TestCase):
    """The write path. A render gate is not a payload gate."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.user = User.objects.create_user(email="laurel@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/osps/{self.osp.id}/modules/{G8}/"
        )

    def _put(self, payload):
        return self.client.put(self._url(), payload, format="json")

    def test_the_api_refuses_to_store_the_attestation_over_an_empty_registry(self):
        response = self._put({"answers": {ATTESTATION: True}})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(ATTESTATION, response.data.get("answers", {}))

        self.osp.refresh_from_db()
        stored = ((self.osp.module_responses or {}).get("modules", {}).get(G8) or {}).get("answers") or {}
        self.assertNotIn(ATTESTATION, stored, "the untrue value must never reach storage")

    def test_a_confirmation_for_a_retired_key_does_not_open_the_gate(self):
        """⛔ The gate must agree with what the PDF PRINTS, not with what `sections` holds.

        The renderer iterates the registry, so a confirmation left behind for a record type that
        has since left it prints nothing — and counting it here would let the attestation through
        over a page with no list on it, which is the exact defect this gate exists to prevent.
        """
        from certifications.services.common_osp_records import CONFIRMATIONS_KEY, OSP_SECTION_KEY

        sections = dict(self.osp.sections or {})
        sections[OSP_SECTION_KEY] = {
            CONFIRMATIONS_KEY: {"a_record_type_we_retired": {"confirmed": True, "confirmed_at": "2026-01-01T00:00:00Z"}}
        }
        self.osp.sections = sections
        self.osp.save(update_fields=["sections"])

        response = self._put({"answers": {ATTESTATION: True}})
        self.assertEqual(response.status_code, 400, response.data)
        # The WRITE path reports under `answers`; `attestations` is the completion path's shape.
        self.assertIn(ATTESTATION, response.data["answers"])

        self.osp.refresh_from_db()
        stored = ((self.osp.module_responses or {}).get("modules", {}).get(G8) or {}).get("answers") or {}
        self.assertNotIn(ATTESTATION, stored, "the untrue value must never reach storage")

    def test_the_same_answer_is_accepted_once_the_required_records_are_confirmed(self):
        _answer_activities(self.osp)
        confirm(self.osp, ["harvest_records", "planting_records"], user=self.user)
        response = self._put({"answers": {ATTESTATION: True}})
        self.assertEqual(response.status_code, 200, response.data)

        self.osp.refresh_from_db()
        stored = ((self.osp.module_responses or {}).get("modules", {}).get(G8) or {}).get("answers") or {}
        self.assertIn(ATTESTATION, stored)

    def test_completion_is_refused_while_the_registry_is_empty(self):
        # Reach completion the way a legacy plan did: answers already stored, then `complete`.
        # Answer the module's other required questions too, so required-field validation cannot
        # mask the gate — a test that passes because a DIFFERENT rule fired proves nothing.
        stamp = {"at": "2026-01-01T00:00:00Z"}
        responses = {
            "modules": {
                G8: {
                    "answers": {
                        ATTESTATION: {"value": True, **stamp},
                        "lot_numbering": {"value": "trazo_lots", **stamp},
                        "import_export_activity": {"value": ["none_no_known_export"], **stamp},
                        # WSDA AGR 2121-O q5/q6/q7, added to page A 2026-09-06. They are
                        # required, so leaving them blank makes required-field validation fire
                        # FIRST and the gate never runs — which is the masking this fixture
                        # exists to rule out.
                        "records_location": {"value": "primary_only", **stamp},
                        "primary_contact_records_access": {"value": "yes", **stamp},
                        "records_maintained_as": {"value": ["electronic"], **stamp},
                    }
                }
            }
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

        response = self._put({"complete": True})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("attestations", response.data)

    def test_a_module_completed_before_the_gate_no_longer_reports_completed(self):
        responses = {
            "modules": {
                G8: {
                    "answers": {ATTESTATION: {"value": True, "at": "2026-01-01T00:00:00Z"}},
                    "completed_at": "2026-01-01T00:00:00Z",
                    "completed_by": self.user.id,
                }
            }
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

        response = self.client.get(
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/osps/{self.osp.id}/modules/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        row = next(r for r in response.data["modules"] if r["key"] == G8)
        self.assertEqual(row["status"], "in_progress", "a green tick here is one a certifier sends back")


class LegacyAttestationInThePacketTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            module_responses={
                "modules": {G8: {"answers": {ATTESTATION: {"value": True, "at": "2026-01-01T00:00:00Z"}}}}
            },
        )

    def test_the_pdf_qualifies_an_attestation_the_plan_does_not_support(self):
        from certifications.services.osp_module_pdf import generate_module_pdf

        pdf = generate_module_pdf(self.osp, G8)
        self.assertTrue(pdf.startswith(b"%PDF"))
        # Assert on the rendered text, not the bytes' shape — `%PDF` alone is the vacuous assertion
        # this codebase has already been bitten by. (Hand-decoding the streams is not enough either:
        # ReportLab ASCII85-encodes them, so a naive zlib pass yields noise that contains neither
        # the string nor its absence meaningfully.)
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            text = "\n".join(page.extract_text() or "" for page in doc.pages)
        self.assertIn("REVIEW", text)
        self.assertIn("not supported by the plan", text)


class TrazoIsNotTheVerifierTests(TestCase):
    """Trazo resolves names; the certifying agent approves materials.

    `compliance.md` allows "verified" only for a USDA Organic Integrity Database match, and CCOF's
    OSP Materials List is a list the CERTIFIER reviews and returns as approved. Copy that said
    otherwise was spread across the module education, the panel label, five compile templates, the
    packet heading, the audit-export heading and both locales — and G3.0 offered "checked … in
    Trazo" as a basis for allowing a seed treatment, which the drift detector explicitly does not
    do.

    Pinned as a source sweep because the claim's danger is exactly that it reappears somewhere new.
    """

    # BOTH locales. The first version of this list held English phrases only, and the Spanish
    # half of the same claim survived the fix — "Trazo verifica cada material…", "Aquí se verifica
    # contra OMRI…", "el estado de verificación" — which is the i18n parity blind spot this
    # codebase has hit before. A guard written in one language guards one language.
    FORBIDDEN = (
        "Trazo verifies",
        "verified materials list",
        "certifier-approved scope",
        "Approved input materials",
        "trazo_verification",
        "Trazo verifica",
        "se verifica contra",
        "estado de verificación",
        "Insumos aprobados",
    )

    def _sources(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        for rel in (
            "certifications/osp_modules/materials_application.py",
            "certifications/osp_modules/g3_0_seeds.py",
            "certifications/services/osp_module_pdf.py",
            "certifications/services/osp_module_compiler.py",
            "history/services/audit_export_service.py",
        ):
            yield rel, (root / rel).read_text()

    def test_no_surface_claims_trazo_verifies_or_approves_a_material(self):
        offenders = [
            f"{rel}: {phrase!r}" for rel, text in self._sources() for phrase in self.FORBIDDEN if phrase in text
        ]
        self.assertEqual(offenders, [], f"claim-safety wording reappeared: {offenders}")

    def test_the_seed_treatment_question_offers_only_the_two_bases_ccof_accepts(self):
        from certifications.osp_modules import MODULES_BY_KEY

        question = next(
            q
            for page in MODULES_BY_KEY["g3_0_seeds"].pages
            for q in page.questions
            if q.key == "treatment_verification"
        )
        self.assertEqual({o.value for o in question.options}, {"omri_wsda", "certifier_approval"})

    def test_the_compiled_sentence_does_not_say_the_treatment_was_verified(self):
        from certifications.osp_modules import MODULES_BY_KEY

        question = next(
            q
            for page in MODULES_BY_KEY["g3_0_seeds"].pages
            for q in page.questions
            if q.key == "treatment_verification"
        )
        self.assertNotIn("verified", question.compiles_to.template.lower())

    def test_the_compiled_narrative_says_the_plan_list_not_a_verified_one(self):
        """Compile it, do not just read the template.

        The sweep above proves the template changed. It does not prove the sentence a certifier
        reads changed — and it did not: seven plans kept "the verified materials list" in their
        stored `narrative_generated` because a submitted or active plan is never recompiled.
        Migration 0033 corrected the stored text; this asserts the compiler cannot reintroduce it.
        """
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_compiler import compile_modules_to_sections
        from company.models import Company, Establishment

        company = Company.objects.create(name="Compile Co")
        establishment = Establishment.objects.create(name="Compile Ranch", company=company, state="OR")
        osp = OrganicSystemPlan.objects.create(
            establishment=establishment,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "modules": {
                    "materials_application": {
                        "answers": {
                            "materials_list_complete": {"value": True},
                            "fertilizers_listed": {"value": True},
                            "pest_disease_weed_listed": {"value": True},
                            "production_aids_listed": {"value": True},
                            "post_harvest_contact_listed": {"value": True},
                        }
                    }
                },
                "parcel_modules": {},
            },
        )
        compile_modules_to_sections(osp)

        narrative = (osp.sections or {}).get("inputs_list", {}).get("narrative_generated", "")
        self.assertIn("materials list on this plan", narrative)
        self.assertNotIn("verified materials list", narrative)

    def test_both_locales_dropped_the_certifier_approved_claim(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "trazo-app" / "src" / "i18n" / "lang"
        for name, forbidden in (
            ("en-US.json", ("certifier approved on this OSP", "Already approved", "Approved inputs")),
            ("es-419.json", ("el certificador aprobó en este OSP", "Ya aprobado", "Insumos aprobados")),
        ):
            path = root / name
            if not path.exists():  # backend-only checkouts
                continue
            data = json.loads(path.read_text())
            for key in ("osp.approvedInputs.cfr", "osp.approvedInputs.title", "osp.approvedInputs.search.alreadyAdded"):
                value = data.get(key, "")
                for phrase in forbidden:
                    self.assertNotIn(phrase, value, f"{name} [{key}] still claims Trazo/certifier approval")

    def test_no_questionnaire_text_in_either_locale_names_trazo_as_the_verifier(self):
        """The structural half, over EVERY string the questionnaire shows, in BOTH locales.

        The phrase list above catches the wording that exists today. This catches the next one
        someone writes — anywhere in a module: module education, page education, question label,
        coaching, placeholder, or option label — and in Spanish as well as English, because the
        Spanish half of this very claim ("Trazo verifica cada material…") survived the English fix
        and was found only on a fresh-eyes re-read.
        """
        # Match TRAZO AS THE SUBJECT of a verify/approve verb, in either language — not merely the
        # co-occurrence of "Trazo" and "approve" in one string. Correct copy says both words in one
        # breath ("Trazo resolves each name … your certifying agent is the one who approves"), and
        # a guard that reddens on correct copy is one someone switches off.
        import re

        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

        # `aprueb` as well as `aprob`: Spanish stem-changing verbs mean "aprueba"/"aprueban" do not
        # share a prefix with "aprobado", and a stem list written from the participle alone misses
        # the present tense — which is the tense a UI claim is written in.
        verbs = r"(?:verif|aprob|aprueb|approv|comprob|check)"
        claim_patterns = (
            # Trazo as the subject: "Trazo verifies", "Trazo verifica", "Trazo also verifies".
            re.compile(rf"\btrazo\b(?:\s+\w+){{0,2}}\s+{verbs}", re.I),
            # Trazo as the place the checking happened, at a distance: "verified by Trazo",
            # "Checked against the National List / OMRI / WSDA in Trazo at logging time",
            # "Verificado contra la Lista Nacional … en Trazo al registrar". Bounded by a sentence
            # end so it cannot reach across into an unrelated clause.
            re.compile(rf"{verbs}\w*[^.]{{0,90}}?\b(?:by|in|por|en)\s+trazo\b", re.I),
        )

        def offending(where, textmap):
            if not textmap:
                return []
            found = []
            for locale, value in textmap.items():
                blob = " ".join(str(value or "").split())
                if any(pattern.search(blob) for pattern in claim_patterns):
                    found.append(f"{where} [{locale}]: {blob[:120]}")
            return found

        offenders = []
        for module in tuple(MODULE_REGISTRY) + (PARCEL_APPLICATION,):
            for block in module.education:
                offenders += offending(f"{module.key} education", block)
            for page in module.pages:
                for block in page.education:
                    offenders += offending(f"{module.key}.{page.key} education", block)
                for question in page.questions:
                    where = f"{module.key}.{question.key}"
                    offenders += offending(f"{where} label", question.label)
                    offenders += offending(f"{where} coaching", question.coaching)
                    offenders += offending(f"{where} placeholder", question.placeholder)
                    for option in question.options:
                        offenders += offending(f"{where} option {option.value}", option.label)

        self.assertEqual(
            offenders,
            [],
            "Questionnaire text names Trazo as the verifier or approver of a material. Trazo "
            "resolves names against OMRI / the WSDA Materials List / the National List; the "
            f"certifying agent approves: {offenders}",
        )


class PlanMaterialsAreOneListTests(TestCase):
    """The packet must not render two materials lists that disagree without saying so.

    One renewal packet carried four renderings of this operation's materials — 7, 9, 9 and 10 rows
    — with an exact-name overlap of ONE, under five attestations that everything in use was
    "entered in this list". The module PDF's 7 came from a renderer that read two of the three
    registries and dropped every WSDA-listed product beneath a heading that said "OMRI / WSDA".
    """

    def setUp(self):
        from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
        from company.models import Company, Establishment

        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.substance = NationalListSubstance.objects.create(substance_name="Lime sulfur", cfr_section="205.601")
        self.omri = OMRIProduct.objects.create(product_name="Entrust SC", omri_id="dow-2900")
        self.wsda = WSDAMaterial.objects.create(brand_name="Serenade Opti", wsda_id="WSDA-REG-BIOAG-2025-003")
        self.osp.approved_national_list_substances.add(self.substance)
        self.osp.approved_omri_products.add(self.omri)
        self.osp.approved_wsda_materials.add(self.wsda)

    def test_plan_materials_reads_all_three_registries(self):
        from certifications.services.plan_materials import plan_materials

        rows = plan_materials(self.osp)
        self.assertEqual({r.source for r in rows}, {"National List", "OMRI", "WSDA"})
        self.assertIn("Serenade Opti", [r.name for r in rows], "the WSDA registry was the one silently dropped")

    def test_the_module_pdf_prints_the_wsda_rows(self):
        from certifications.services.osp_module_pdf import generate_module_pdf

        text = _pdf_text_local(generate_module_pdf(self.osp, "materials_application"))
        for expected in ("Lime sulfur", "Entrust SC", "Serenade Opti"):
            self.assertIn(expected, text, f"{expected} is on the plan but missing from the packet")

    def test_a_logged_product_absent_from_the_plan_is_reported_as_unmatched(self):
        from datetime import date

        from history.models import ChemicalEvent, History
        from product.models import Parcel, Product

        product = Product.objects.create(name="Blueberry")
        parcel = Parcel.objects.create(name="Home Field East", establishment=self.establishment, area=5.0)
        history = History.objects.create(
            name="2026 Season", parcel=parcel, product=product, start_date=date(2026, 3, 1)
        )
        ChemicalEvent.objects.create(history=history, date=date(2026, 6, 1), commercial_name="Rexius Organic Compost")

        from certifications.services.plan_materials import unmatched_logged_materials

        self.assertIn("Rexius Organic Compost", unmatched_logged_materials(self.osp))

        from certifications.services.osp_module_pdf import generate_module_pdf

        text = _pdf_text_local(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("REVIEW", text)
        self.assertIn("Rexius Organic Compost", text)

    def test_unmatched_is_never_worded_as_unapproved(self):
        # A brand ("Rex Lime Sulfur") and the substance entry covering it ("Lime sulfur") read
        # differently. Calling the difference an approval finding would invent one.
        from certifications.services import plan_materials as module

        source = __import__("pathlib").Path(module.__file__).read_text()
        self.assertIn("UNMATCHED, not unapproved", source)


def _pdf_text_local(data: bytes) -> str:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)
