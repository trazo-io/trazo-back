"""The buyer-page input claim, previewed for a draft the wizard has not saved yet.

🔴 2026-09-03, found while filming the demo. The grower logged an Entrust application, attached
the OMRI listing with "Use this listing", and opened the wizard's Preview ("How shoppers will see
this activity"). The chip read "Organic-approved · grower-reported".

The browser was right to refuse: `ConsumerEventCard.ORGANIC_STATUS_KEYS` maps every
`organic_approved` value to the grower-reported wording precisely because the client cannot see
the OMRI or WSDA catalogs, and a listing claim decided there is the unearned certification-mark
claim `claim_authority` was written to end (2026-08-09). The defect was that the preview had
nothing to ask.

These tests pin the two properties that make the dry run safe to exist:

  1. It answers with the SAME decision the saved record will get, from the same chokepoint. If it
     ever grows its own opinion, the chokepoint has two doors.
  2. It cannot be used to manufacture a claim. The draft is client-supplied, so an OMRI id is a
     claim about a catalog row until the row is shown to exist.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
from history.services.claim_preview import preview_input_status

PREVIEW_URL = "/api/input-status-preview/"


class InputStatusPreviewServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.omri = OMRIProduct.objects.create(
            omri_id="OMRI-ENT-1",
            product_name="Entrust SC",
            manufacturer="Corteva",
        )
        cls.wsda = WSDAMaterial.objects.create(
            wsda_id="WSDA-ENT-1",
            brand_name="Entrust SC",
        )
        NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            status="allowed",
        )
        NationalListSubstance.objects.create(
            substance_name="Calcium chloride",
            substance_name_normalized="calcium chloride",
            cfr_section="205.602",
            status="prohibited",
        )

    def test_attached_omri_listing_earns_the_listing_claim(self):
        # The exact draft that was on screen: the listing attached, the basis recorded.
        status = preview_input_status(
            {
                "commercial_name": "Entrust SC",
                "organic_approved": "omri_listed",
                "omri_product": self.omri.pk,
            }
        )
        self.assertEqual(status["status"], "omri_listed")

    def test_the_same_draft_without_the_listing_is_grower_reported(self):
        # Anti-vacuity for the test above: the dropdown ALONE must never earn OMRI's name.
        status = preview_input_status({"commercial_name": "Entrust SC", "organic_approved": "omri_listed"})
        self.assertEqual(status["status"], "organic_approved")

    def test_an_omri_id_that_names_no_row_earns_nothing(self):
        # The draft is client-supplied. If an unknown id resolved to a listing, this endpoint
        # would be the easiest place in the product to manufacture a third-party claim.
        status = preview_input_status(
            {
                "commercial_name": "Entrust SC",
                "organic_approved": "omri_listed",
                "omri_product": self.omri.pk + 9999,
            }
        )
        self.assertEqual(status["status"], "organic_approved")
        for junk in ("not-a-number", "", None, 0):
            self.assertEqual(
                preview_input_status({"commercial_name": "Entrust SC", "omri_product": junk})["status"],
                "unclassified",
            )

    def test_wsda_is_spoken_in_wsda_s_own_name(self):
        status = preview_input_status({"commercial_name": "Entrust SC", "wsda_material": self.wsda.pk})
        self.assertEqual(status["status"], "wsda_listed")

    def test_it_runs_the_national_list_classifier_the_saved_record_runs(self):
        # No listing attached and no dropdown answer, but the active ingredient is on
        # § 205.601. The saved record gets that citation from a pre_save receiver; the preview
        # must not be blind to it, or it would understate the saved page.
        status = preview_input_status({"commercial_name": "Entrust SC", "active_ingredient": "Spinosad"})
        self.assertEqual(status["status"], "national_list_allowed")

    def test_a_prohibited_substance_is_not_softened(self):
        status = preview_input_status({"commercial_name": "Calcium chloride"})
        self.assertEqual(status["status"], "conventional_documented")

    def test_an_explicit_not_organic_answer_outranks_a_catalog_match(self):
        # A grower saying the input was not organic-approved is a first-party statement, and the
        # server already resolves the disagreement that way. The preview shows the same thing,
        # which is what lets the form leave the two facts independent.
        status = preview_input_status(
            {
                "commercial_name": "Entrust SC",
                "organic_approved": "not_organic",
                "omri_product": self.omri.pk,
            }
        )
        self.assertEqual(status["status"], "conventional_documented")

    def test_it_writes_nothing(self):
        before = OMRIProduct.objects.count(), NationalListSubstance.objects.count()
        preview_input_status({"commercial_name": "Entrust SC", "active_ingredient": "Spinosad"})
        self.assertEqual((OMRIProduct.objects.count(), NationalListSubstance.objects.count()), before)

    def test_it_agrees_with_the_resolver_the_public_payload_uses(self):
        # The property that matters most: same chokepoint, same answer. Built here as a stub
        # rather than a saved event so the comparison is of the DECISION, not of the plumbing.
        from history.services.claim_resolver import resolve_input_status

        class _Saved:
            omri_product_id = self.omri.pk
            wsda_material_id = None
            national_list_substance = None
            organic_approved = "omri_listed"
            restricted_use_pesticide = False
            extra_data = {}

        self.assertEqual(
            preview_input_status(
                {
                    "commercial_name": "Entrust SC",
                    "organic_approved": "omri_listed",
                    "omri_product": self.omri.pk,
                }
            ),
            resolve_input_status(_Saved()),
        )


class InputStatusPreviewEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="preview@example.com", password="E2Epass!2026")
        cls.omri = OMRIProduct.objects.create(omri_id="OMRI-ENT-2", product_name="Entrust SC")

    def setUp(self):
        # DRF's own client: auth here is cookie-based JWT (see .claude/rules/backend.md), so
        # Django's session `force_login` does not authenticate this endpoint.
        self.api = APIClient()

    def _post(self, payload):
        return self.api.post(PREVIEW_URL, data=json.dumps(payload), content_type="application/json")

    def test_anonymous_callers_are_refused(self):
        self.assertIn(self._post({"commercial_name": "Entrust SC"}).status_code, (401, 403))

    def test_it_returns_the_same_shape_the_public_payload_carries(self):
        self.api.force_authenticate(user=self.user)
        response = self._post(
            {"commercial_name": "Entrust SC", "omri_product": self.omri.pk, "organic_approved": "omri_listed"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.json().keys()), ["label", "status"])
        self.assertEqual(response.json()["status"], "omri_listed")

    def test_an_empty_draft_answers_documented_rather_than_erroring(self):
        # The wizard calls this while the farmer is still typing.
        self.api.force_authenticate(user=self.user)
        response = self._post({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unclassified")

    def test_it_reads_only_the_fields_that_decide_the_claim(self):
        # An allow-list, so this cannot grow into a general "evaluate arbitrary event data"
        # surface. A key outside it is ignored, never echoed and never acted on.
        self.api.force_authenticate(user=self.user)
        response = self._post({"commercial_name": "Entrust SC", "omri_product": self.omri.pk, "volume_numeric": 40})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("volume_numeric", response.json())
