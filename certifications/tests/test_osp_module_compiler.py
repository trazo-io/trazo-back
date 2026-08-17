"""
Compiler tests (WS-2.3) — module answers → § 205.201(a) narratives.

The properties that matter:

  1. Deterministic template-fill from the operator's own answers — the compiled prose
     restates exactly what was selected, as the EN labels the operator saw.
  2. Hidden branches never compile — a stale answer on a collapsed branch must not leak
     a sentence into a certifier-bound narrative.
  3. Manual text is the operator's: composition appends it after generated prose, a
     client PATCH of `narrative` lands in the manual field, and a client echoing back
     the composed text changes nothing.
  4. The submit gate is unchanged in kind: floor + padding still apply to the composed
     `narrative`; module-generated prose counts toward the floor because it is operator
     content, and it must not trip the padding detector.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from certifications.services.osp_module_compiler import (
    compile_module_contributions,
    compile_modules_to_sections,
    normalize_incoming_sections,
)
from company.models import Company, Establishment
from users.models import User, WorksIn


def _entry(answers=None, not_applicable=False, na_at=None):
    return {
        "status": "in_progress",
        "not_applicable": not_applicable,
        "na_attestation": {"by": 1, "at": na_at} if not_applicable else None,
        "answers": {k: {"value": v, "at": "2026-08-08T10:00:00"} for k, v in (answers or {}).items()},
        "completed_at": None,
        "completed_by": None,
        "definition_version": "test",
    }


class CompilerUnitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Compiler Farm")
        self.establishment = Establishment.objects.create(name="Ranch", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1)

    def test_answers_compile_to_module_headed_paragraph(self):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"g3_0_seeds": _entry({"seeds_used": ["organic_untreated"], "seedlings_used": ["none"]})},
            "parcel_modules": {},
        }
        contributions = compile_module_contributions(self.osp)
        paragraph = contributions["practices_procedures"][0]
        self.assertIn("[G3.0 Seeds & Planting Stock]", paragraph)
        self.assertIn("Seeds used in organic production: Organic, untreated.", paragraph)
        self.assertIn("Annual seedlings: None used.", paragraph)

    def test_hidden_branch_answers_do_not_compile(self):
        # Farmer once selected non-organic seed (revealing B), answered it, then
        # switched back to "none" — the stale B answer must not leak.
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {
                "g3_0_seeds": _entry(
                    {
                        "seeds_used": ["none"],
                        "ca_search_before_use": "documented_search",
                    }
                )
            },
            "parcel_modules": {},
        }
        contributions = compile_module_contributions(self.osp)
        text = "\n".join(contributions.get("practices_procedures", []))
        self.assertNotIn("Commercial-availability", text)

    def test_na_module_compiles_one_attested_line(self):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"g3_0_seeds": _entry(not_applicable=True, na_at="2026-08-08T10:00:00")},
            "parcel_modules": {},
        }
        contributions = compile_module_contributions(self.osp)
        paragraph = contributions["practices_procedures"][0]
        self.assertIn("Not applicable — reviewed and attested by the operator on 2026-08-08.", paragraph)

    def test_compile_rule_section_override_routes_to_inputs_list(self):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {
                "g3_0_seeds": _entry(
                    {
                        "seeds_used": ["organic_treated"],
                        "treatment_verification": ["omri_wsda"],
                        "treatments_on_inputs_list": True,
                    }
                )
            },
            "parcel_modules": {},
        }
        contributions = compile_module_contributions(self.osp)
        inputs_text = "\n".join(contributions["inputs_list"])
        self.assertIn("Seed treatment materials on the OSP inputs list: Yes.", inputs_text)
        practices_text = "\n".join(contributions["practices_procedures"])
        self.assertNotIn("inputs list: Yes", practices_text)

    def test_compose_appends_manual_after_generated_and_preserves_legacy(self):
        # Legacy shape: bare narrative — becomes manual on first compile.
        sections = {k: {"narrative": "", "last_updated": None} for k in OSP_SECTION_KEYS}
        sections["practices_procedures"]["narrative"] = "We farm 12 acres of walnuts on the home ranch."
        self.osp.sections = sections
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"g3_0_seeds": _entry({"seeds_used": ["organic_untreated"]})},
            "parcel_modules": {},
        }
        changed = compile_modules_to_sections(self.osp)
        self.assertTrue(changed)
        section = self.osp.sections["practices_procedures"]
        self.assertEqual(section["narrative_manual"], "We farm 12 acres of walnuts on the home ranch.")
        self.assertIn("[G3.0", section["narrative_generated"])
        self.assertTrue(section["narrative"].startswith("[G3.0"))
        self.assertTrue(section["narrative"].endswith("home ranch."))

    def test_idempotent(self):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"g3_0_seeds": _entry({"seeds_used": ["none"]})},
            "parcel_modules": {},
        }
        self.assertTrue(compile_modules_to_sections(self.osp))
        self.assertFalse(compile_modules_to_sections(self.osp))

    def test_padding_detector_not_tripped_by_generated_prose(self):
        from history.services.audit_export_service import looks_like_padding

        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {
                "g3_0_seeds": _entry(
                    {
                        "seeds_used": ["organic_untreated", "organic_treated"],
                        "seedlings_used": ["purchased_organic"],
                        "planting_stock_used": ["organic"],
                        "treatment_verification": ["omri_wsda", "trazo_verification"],
                        "treatments_on_inputs_list": True,
                        "grafts_stock": "no",
                    }
                )
            },
            "parcel_modules": {},
        }
        compile_modules_to_sections(self.osp)
        generated = self.osp.sections["practices_procedures"]["narrative_generated"]
        self.assertTrue(generated)
        self.assertFalse(looks_like_padding(generated))


class NormalizeIncomingSectionsTests(TestCase):
    def setUp(self):
        self.stored = {
            "practices_procedures": {
                "narrative": "[G3.0 Seeds & Planting Stock]\nSeeds used in organic production: Organic, untreated.\n\nOur own words.",
                "narrative_generated": "[G3.0 Seeds & Planting Stock]\nSeeds used in organic production: Organic, untreated.",
                "narrative_manual": "Our own words.",
            }
        }

    def test_echoed_composed_narrative_keeps_manual_unchanged(self):
        incoming = {"practices_procedures": {"narrative": self.stored["practices_procedures"]["narrative"]}}
        out = normalize_incoming_sections(self.stored, incoming)
        self.assertEqual(out["practices_procedures"]["narrative_manual"], "Our own words.")

    def test_edited_narrative_lands_in_manual_stripping_generated_prefix(self):
        edited = self.stored["practices_procedures"]["narrative"] + "\n\nNew manual sentence."
        out = normalize_incoming_sections(self.stored, {"practices_procedures": {"narrative": edited}})
        self.assertEqual(
            out["practices_procedures"]["narrative_manual"],
            "Our own words.\n\nNew manual sentence.",
        )
        # Generated prose is preserved verbatim, composition rebuilt.
        self.assertTrue(out["practices_procedures"]["narrative"].startswith("[G3.0"))

    def test_new_client_narrative_manual_taken_verbatim(self):
        out = normalize_incoming_sections(self.stored, {"practices_procedures": {"narrative_manual": "Replaced."}})
        self.assertEqual(out["practices_procedures"]["narrative_manual"], "Replaced.")
        self.assertIn("Replaced.", out["practices_procedures"]["narrative"])


class CompilerAPIFlowTests(TestCase):
    """End-to-end: module PUT recompiles; PATCH writes manual; submit gate coherent."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Flow Farm")
        self.user = User.objects.create_user(email="flow@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Ranch", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _base(self):
        return f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/osps/{self.osp.id}"

    def test_module_put_recompiles_sections(self):
        r = self.client.put(
            f"{self._base()}/modules/g3_0_seeds/",
            {"answers": {"seeds_used": ["organic_untreated"]}},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.osp.refresh_from_db()
        section = self.osp.sections["practices_procedures"]
        self.assertIn("Organic, untreated", section["narrative_generated"])
        self.assertIn("Organic, untreated", section["narrative"])

    def test_patch_narrative_becomes_manual_and_survives_recompile(self):
        self.client.put(
            f"{self._base()}/modules/g3_0_seeds/",
            {"answers": {"seeds_used": ["organic_untreated"]}},
            format="json",
        )
        self.osp.refresh_from_db()
        composed = self.osp.sections["practices_procedures"]["narrative"]
        # The serializer requires the full six-key object (existing contract) — echo
        # what was read and edit one section, exactly like the section editor does.
        payload = {k: {"narrative": (v or {}).get("narrative", "")} for k, v in self.osp.sections.items()}
        payload["practices_procedures"] = {"narrative": composed + "\n\nHand-written detail."}
        r = self.client.patch(f"{self._base()}/", {"sections": payload}, format="json")
        self.assertEqual(r.status_code, 200)
        self.osp.refresh_from_db()
        section = self.osp.sections["practices_procedures"]
        self.assertEqual(section["narrative_manual"], "Hand-written detail.")
        # Another module write must keep the manual text.
        self.client.put(
            f"{self._base()}/modules/g3_0_seeds/",
            {"answers": {"seedlings_used": ["none"]}},
            format="json",
        )
        self.osp.refresh_from_db()
        section = self.osp.sections["practices_procedures"]
        self.assertEqual(section["narrative_manual"], "Hand-written detail.")
        self.assertIn("Annual seedlings: None used.", section["narrative"])

    def test_submit_gate_floor_still_enforced_on_composed_narrative(self):
        # Thin module answers alone won't clear six 400-char sections — the gate must
        # still refuse, listing the empty sections (regression on the floor).
        self.client.put(
            f"{self._base()}/modules/g3_0_seeds/",
            {"answers": {"seeds_used": ["none"], "seedlings_used": ["none"], "planting_stock_used": ["none"]}},
            format="json",
        )
        r = self.client.post(f"{self._base()}/submit/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("missing_sections", r.data)
        self.assertIn("additional_certifier_info", r.data["missing_sections"])
