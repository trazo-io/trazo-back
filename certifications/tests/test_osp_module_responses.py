"""
Guided OSP module response API tests (WS-2.2).

The properties that matter:

  1. Answers are the operator's writes only — enveloped, merged, deletable — and the
     serializer exposes module_responses read-only (a PATCH cannot smuggle answers in).
  2. The draft edit-lock applies: module answers on a submitted OSP are an attested
     record, so writes are refused exactly like section edits.
  3. N/A is a stamped attestation (who/when), refused on modules with no N/A path.
  4. complete=True runs required-if-visible validation server-side, and any later
     content change clears the completion stamp — a changed module must be re-completed.
  5. new-version clones module answers — next season starts from last year's.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.osp_modules import CONTENT_VERSION
from company.models import Company, Establishment
from users.models import User, WorksIn


class ModuleResponseAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Module Farm")
        self.user = User.objects.create_user(email="modresp@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _base(self):
        return f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/osps/{self.osp.id}"

    def _module_url(self, key="g3_0_seeds"):
        return f"{self._base()}/modules/{key}/"

    # --- defaults & listing ---------------------------------------------------------

    def test_new_osp_has_empty_module_responses(self):
        self.assertEqual(
            self.osp.module_responses,
            {"schema_version": 1, "modules": {}, "parcel_modules": {}},
        )

    def test_modules_list_shows_every_registry_module_not_started(self):
        response = self.client.get(f"{self._base()}/modules/")
        self.assertEqual(response.status_code, 200)
        rows = response.data["modules"]
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r["status"] == "not_started" for r in rows))
        g3 = next(r for r in rows if r["key"] == "g3_0_seeds")
        self.assertEqual(g3["code"], "G3.0")
        self.assertEqual(g3["progress"]["answered"], 0)

    def test_module_get_returns_definition_and_empty_answers(self):
        response = self.client.get(self._module_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["definition"]["key"], "g3_0_seeds")
        self.assertEqual(response.data["answers"], {})
        self.assertEqual(response.data["suggestions"], {})

    def test_unknown_module_404(self):
        self.assertEqual(self.client.get(self._module_url("g99_bogus")).status_code, 404)

    # --- writes ---------------------------------------------------------------------

    def test_put_saves_enveloped_answers_and_merges(self):
        r1 = self.client.put(self._module_url(), {"answers": {"seeds_used": ["organic_untreated"]}}, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["response"]["status"], "in_progress")
        self.assertEqual(r1.data["answers"]["seeds_used"]["value"], ["organic_untreated"])
        self.assertIn("at", r1.data["answers"]["seeds_used"])

        r2 = self.client.put(self._module_url(), {"answers": {"seedlings_used": ["none"]}}, format="json")
        self.assertEqual(set(r2.data["answers"]), {"seeds_used", "seedlings_used"})

        # null deletes
        r3 = self.client.put(self._module_url(), {"answers": {"seeds_used": None}}, format="json")
        self.assertEqual(set(r3.data["answers"]), {"seedlings_used"})

    def test_unknown_answer_key_400(self):
        r = self.client.put(self._module_url(), {"answers": {"bogus": 1}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("bogus", str(r.data))

    def test_invalid_choice_value_400(self):
        r = self.client.put(self._module_url(), {"answers": {"seeds_used": ["glyphosate"]}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_boolean_question_rejects_non_boolean(self):
        # The string "no" is truthy — unvalidated it would compile "…: Yes." into a
        # certifier-bound narrative. Types are enforced at the write boundary.
        r = self.client.put(
            self._module_url(),
            {"answers": {"treatments_on_inputs_list": "no"}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("treatments_on_inputs_list", str(r.data))

    def test_exclusive_option_cannot_combine(self):
        # "None used" + a real selection would compile a self-contradictory sentence.
        r = self.client.put(
            self._module_url(),
            {"answers": {"seeds_used": ["none", "organic_untreated"]}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("none-of-the-above", str(r.data))

    def test_serializer_patch_cannot_write_module_responses(self):
        r = self.client.patch(
            f"{self._base()}/",
            {
                "module_responses": {
                    "schema_version": 1,
                    "modules": {"g3_0_seeds": {"answers": {"seeds_used": {"value": ["none"]}}}},
                    "parcel_modules": {},
                }
            },
            format="json",
        )
        self.assertIn(r.status_code, (200, 202))
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.module_responses["modules"], {})

    # --- N/A attestation ------------------------------------------------------------

    def test_na_attestation_stamps_user_and_time(self):
        r = self.client.put(self._module_url(), {"not_applicable": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["response"]["status"], "not_applicable")
        att = r.data["response"]["na_attestation"]
        self.assertEqual(att["by"], self.user.id)
        self.assertTrue(att["at"])

    def test_na_refused_on_module_without_na_path(self):
        r = self.client.put(self._module_url("g4_0_rotation_soil"), {"not_applicable": True}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_na_false_clears_attestation(self):
        self.client.put(self._module_url(), {"not_applicable": True}, format="json")
        r = self.client.put(self._module_url(), {"not_applicable": False}, format="json")
        self.assertIsNone(r.data["response"]["na_attestation"])
        self.assertEqual(r.data["response"]["status"], "not_started")

    # --- completion -----------------------------------------------------------------

    def _answer_page_a_all_none(self):
        return self.client.put(
            self._module_url(),
            {
                "answers": {
                    "seeds_used": ["none"],
                    "seedlings_used": ["none"],
                    "planting_stock_used": ["none"],
                }
            },
            format="json",
        )

    def test_complete_fails_listing_missing_keys(self):
        r = self.client.put(self._module_url(), {"complete": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("seeds_used", r.data["missing"])

    def test_complete_succeeds_and_stamps(self):
        self._answer_page_a_all_none()
        r = self.client.put(self._module_url(), {"complete": True}, format="json")
        self.assertEqual(r.status_code, 200)
        row = r.data["response"]
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["completed_by"], self.user.id)
        self.assertEqual(row["definition_version"], CONTENT_VERSION)

    def test_complete_via_na_attestation(self):
        r = self.client.put(self._module_url(), {"not_applicable": True, "complete": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["response"]["status"], "not_applicable")
        self.assertIsNotNone(r.data["response"]["completed_at"])

    def test_content_change_after_completion_clears_stamp(self):
        self._answer_page_a_all_none()
        self.client.put(self._module_url(), {"complete": True}, format="json")
        r = self.client.put(
            self._module_url(),
            {"answers": {"seeds_used": ["organic_untreated"]}},
            format="json",
        )
        self.assertIsNone(r.data["response"]["completed_at"])
        self.assertEqual(r.data["response"]["status"], "in_progress")

    def test_identical_echo_does_not_clear_completion(self):
        # Autosave clients re-PUT what they read. An answer identical to the stored
        # value is not a content change and must not invalidate the completion stamp.
        self._answer_page_a_all_none()
        self.client.put(self._module_url(), {"complete": True}, format="json")
        r = self.client.put(
            self._module_url(),
            {"answers": {"seeds_used": ["none"]}},
            format="json",
        )
        self.assertIsNotNone(r.data["response"]["completed_at"])
        self.assertEqual(r.data["response"]["status"], "completed")

    def test_deleting_absent_answer_is_not_a_change(self):
        self._answer_page_a_all_none()
        self.client.put(self._module_url(), {"complete": True}, format="json")
        r = self.client.put(
            self._module_url(),
            {"answers": {"gmo_documentation": None}},
            format="json",
        )
        self.assertIsNotNone(r.data["response"]["completed_at"])

    # --- lifecycle lock -------------------------------------------------------------

    def test_writes_refused_outside_draft(self):
        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])
        r = self.client.put(self._module_url(), {"answers": {"seeds_used": ["none"]}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("new version", str(r.data).lower())

    def test_reads_allowed_outside_draft(self):
        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])
        self.assertEqual(self.client.get(self._module_url()).status_code, 200)

    # --- new-version clone ----------------------------------------------------------

    def test_new_version_clones_module_responses(self):
        self._answer_page_a_all_none()
        self.client.put(self._module_url(), {"complete": True}, format="json")
        r = self.client.post(f"{self._base()}/new-version/")
        self.assertEqual(r.status_code, 201)
        clone = OrganicSystemPlan.objects.get(pk=r.data["id"])
        entry = clone.module_responses["modules"]["g3_0_seeds"]
        self.assertEqual(entry["answers"]["seeds_used"]["value"], ["none"])
        self.assertIsNotNone(entry["completed_at"])

    def test_new_version_carries_the_approved_inputs_registry(self):
        """The materials list is an answer too, and the dialog promises to copy every answer.

        🔴 Found 2026-08-21 on a pilot renewal: the clone copied `sections` and
        `module_responses` and stopped, so v2 opened with an EMPTY approved-inputs registry
        while v1 held eight verified entries. The § 205.201(a)(2) narrative is compiled from
        that list, and the audit dossier duly reported "No approved-inputs list is on file for
        this operation" — about a plan that had one. An operator who submits the new version
        has filed a plan with no materials list at all.
        """
        substance = NationalListSubstance.objects.create(
            substance_name="Elemental sulfur", cfr_section="205.601", status="allowed"
        )
        omri = OMRIProduct.objects.create(product_name="Entrust SC", omri_id="dow-2900")
        wsda = WSDAMaterial.objects.create(brand_name="Serenade Opti", wsda_id="WSDA-REG-BIOAG-2025-003")
        self.osp.approved_national_list_substances.add(substance)
        self.osp.approved_omri_products.add(omri)
        self.osp.approved_wsda_materials.add(wsda)

        r = self.client.post(f"{self._base()}/new-version/")
        self.assertEqual(r.status_code, 201)
        clone = OrganicSystemPlan.objects.get(pk=r.data["id"])

        self.assertEqual(list(clone.approved_national_list_substances.all()), [substance])
        self.assertEqual(list(clone.approved_omri_products.all()), [omri])
        self.assertEqual(
            list(clone.approved_wsda_materials.all()),
            [wsda],
            "WSDA entries are co-equal with OMRI and must carry across too",
        )
        # The source keeps its own list — a clone is not a move.
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.approved_omri_products.count(), 1)

    # --- roles ----------------------------------------------------------------------

    def test_viewer_can_read_but_not_write(self):
        viewer = User.objects.create_user(email="viewer@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)
        self.assertEqual(self.client.get(self._module_url()).status_code, 200)
        r = self.client.put(self._module_url(), {"answers": {"seeds_used": ["none"]}}, format="json")
        self.assertEqual(r.status_code, 403)


class StaleCompletionTests(TestCase):
    """A definition change must not leave a green tick on an incomplete module.

    Adding a required question to a shipped module makes every previously-completed
    answer set incomplete. `completed_at` stays in storage as the audit record of when
    the operator first completed it, but reporting "completed" while required questions
    are unanswered puts a tick on a module the certifier will send back. Found when
    G4.2 gained three questions on 2026-08-10 and stayed green.
    """

    def _status(self, entry, module_key="g4_2_natural_resources"):
        from certifications.osp_modules import MODULES_BY_KEY
        from certifications.views import OrganicSystemPlanViewSet

        return OrganicSystemPlanViewSet._module_status(entry, MODULES_BY_KEY[module_key])

    def test_completed_module_missing_new_required_answers_reports_in_progress(self):
        entry = {"completed_at": "2026-08-09T00:00:00Z", "answers": {}}
        self.assertEqual(self._status(entry), "in_progress")

    def test_not_applicable_still_wins(self):
        entry = {"not_applicable": True, "completed_at": None, "answers": {}}
        self.assertEqual(self._status(entry), "not_applicable")

    def test_status_without_a_module_is_unchanged(self):
        """Callers that cannot supply the module keep the stamped behaviour."""
        from certifications.views import OrganicSystemPlanViewSet

        entry = {"completed_at": "2026-08-09T00:00:00Z", "answers": {}}
        self.assertEqual(OrganicSystemPlanViewSet._module_status(entry), "completed")
