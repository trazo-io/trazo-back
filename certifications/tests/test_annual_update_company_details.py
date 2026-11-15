"""§ 205.406(a)(3): the company-details step of the annual update.

WHY THIS EXISTS
---------------
(a)(3) asks for "additions to or deletions from the information required pursuant to
§ 205.401(b)": the responsible person, the business name, address and telephone number. Until
2026-11-02 the filing answered it with free text and an "unchanged" tick, and nothing read the
company record. The step shows what Trazo holds; each detail is confirmed or changed; a change
writes the record through its own update serializer and appends a dated old -> new line to the
filing. These tests hold the rules that make that honest: every detail answered before
"unchanged" is set, a viewer cannot write, a signed revision refuses, the step only reaches the
filing's own records, and a detail Trazo does not hold is typed, never filled in.
"""

from datetime import datetime
from datetime import timezone as dt_tz

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.application_info_review import DETAILS
from certifications.services.osp_module_pdf import APPLICATION_INFO_KEY, _application_info_sentence
from company.models import Company, Establishment
from users.models import User, WorksIn


def _all_correct(**overrides):
    answers = {d.key: {"status": "correct"} for d in DETAILS}
    answers.update(overrides)
    return {"answers": answers}


class _Step(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="ca@cd.test", password="x", is_verified=True)
        self.company = Company.objects.create(
            name="Upper Terrace Orchards LLC", tradename="Upper Terrace", contact_phone="5415550100"
        )
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Upper Terrace",
            company=self.company,
            contact_person="Laurel Brandt",
            address="1200 Orchard Rd",
            city="Hood River",
            state="OR",
            zip_code="97031",
            phone="5415550111",
            contact_email="laurel@upperterrace.test",
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.admin
        )
        self.filing = OSPAnnualUpdate.objects.create(
            prior_osp=self.osp,
            reporting_year=2026,
            created_by=self.admin,
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )
        self.client.force_authenticate(user=self.admin)

    def _url(self, filing=None, company=None, est=None):
        filing = filing or self.filing
        return (
            f"/api/companies/{(company or self.company).pk}/establishments/{(est or self.est).pk}"
            f"/osp-annual-updates/{filing.pk}/company-details/"
        )

    def _post(self, body, **kw):
        return self.client.post(self._url(**kw), body, format="json")


class ShowsWhatTrazoHoldsTests(_Step):
    def test_get_lists_every_detail_with_its_record(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        rows = {r["key"]: r for r in res.json()["details"]}
        self.assertEqual(list(rows), [d.key for d in DETAILS])
        self.assertEqual(rows["legal_name"]["value"], "Upper Terrace Orchards LLC")
        self.assertEqual(rows["legal_name"]["source"], "company.name")
        self.assertEqual(rows["responsible_person"]["value"], "Laurel Brandt")
        self.assertEqual(rows["phone"]["source"], "establishment.phone")
        self.assertFalse(res.json()["attested_unchanged"])

    def test_a_detail_trazo_does_not_hold_reads_as_not_held(self):
        """Never fabricated: no phone on the farm or the company prints as not held, not as the
        account's or anyone else's number."""
        Establishment.objects.filter(pk=self.est.pk).update(phone="", contact_phone=None)
        Company.objects.filter(pk=self.company.pk).update(contact_phone=None)
        rows = {r["key"]: r for r in self.client.get(self._url()).json()["details"]}
        self.assertEqual(rows["phone"]["value"], "")
        self.assertFalse(rows["phone"]["held"])
        self.assertEqual(rows["phone"]["source"], "")

    def test_phone_falls_back_in_the_covers_order(self):
        Establishment.objects.filter(pk=self.est.pk).update(phone="")
        rows = {r["key"]: r for r in self.client.get(self._url()).json()["details"]}
        self.assertEqual(rows["phone"]["value"], "5415550100")
        self.assertEqual(rows["phone"]["source"], "company.contact_phone")


class ConfirmAllTests(_Step):
    def test_every_detail_confirmed_sets_the_unchanged_attestation(self):
        res = self._post(_all_correct())
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        self.filing.refresh_from_db()
        self.assertIs(self.filing.sections_unchanged_attestation.get(APPLICATION_INFO_KEY), True)
        self.assertEqual(self.filing.application_info_changes, "")
        self.assertTrue(res.json()["attested_unchanged"])
        self.assertIn("No changes", _application_info_sentence(self.filing))

    def test_an_unanswered_detail_is_never_read_as_unchanged(self):
        body = _all_correct()
        del body["answers"]["phone"]
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone", str(res.json()["answers"]))
        self.filing.refresh_from_db()
        self.assertNotIn(APPLICATION_INFO_KEY, self.filing.sections_unchanged_attestation or {})

    def test_confirming_over_listed_changes_leaves_the_changes_standing(self):
        self.filing.application_info_changes = "New farm manager: Luis Ortega."
        self.filing.save()
        self.assertEqual(self._post(_all_correct()).status_code, status.HTTP_200_OK)
        self.filing.refresh_from_db()
        self.assertNotIn(APPLICATION_INFO_KEY, self.filing.sections_unchanged_attestation or {})
        self.assertEqual(self.filing.application_info_changes, "New farm manager: Luis Ortega.")

    def test_a_required_detail_trazo_does_not_hold_must_be_typed(self):
        Establishment.objects.filter(pk=self.est.pk).update(contact_person=None)
        res = self._post(_all_correct())
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("responsible_person", res.json()["answers"])
        typed = self._post(_all_correct(responsible_person={"status": "correct", "value": "Laurel Brandt"}))
        self.assertEqual(typed.status_code, status.HTTP_200_OK, typed.content[:300])
        self.est.refresh_from_db()
        self.assertEqual(self.est.contact_person, "Laurel Brandt")
        self.filing.refresh_from_db()
        # Already on file with the agent, missing only in Trazo: recorded, not reported as a change.
        self.assertEqual(self.filing.application_info_changes, "")
        self.assertIs(self.filing.sections_unchanged_attestation.get(APPLICATION_INFO_KEY), True)

    def test_an_optional_detail_may_be_confirmed_empty(self):
        Company.objects.filter(pk=self.company.pk).update(tradename=None)
        self.assertEqual(self._post(_all_correct()).status_code, status.HTTP_200_OK)


class EditWritesTheRecordAndTheFilingTests(_Step):
    def test_a_change_writes_the_farm_and_appends_a_dated_line(self):
        res = self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        self.est.refresh_from_db()
        self.assertEqual(self.est.phone, "(541) 555-0199")
        self.filing.refresh_from_db()
        today = timezone.localdate().isoformat()
        self.assertEqual(
            self.filing.application_info_changes, f"{today}: Phone changed from 5415550111 to (541) 555-0199."
        )
        self.assertNotIn(APPLICATION_INFO_KEY, self.filing.sections_unchanged_attestation or {})

    def test_lines_append_to_what_the_filing_already_says(self):
        self.filing.application_info_changes = "New farm manager: Luis Ortega."
        self.filing.sections_unchanged_attestation = {APPLICATION_INFO_KEY: True, "practices_procedures": True}
        self.filing.save()
        self._post(
            _all_correct(
                legal_name={"status": "changed", "value": "Upper Terrace Farms LLC"},
                state={"status": "changed", "value": "Washington"},
            )
        )
        self.filing.refresh_from_db()
        lines = self.filing.application_info_changes.splitlines()
        self.assertEqual(lines[0], "New farm manager: Luis Ortega.")
        self.assertTrue(
            lines[1].endswith("Business name changed from Upper Terrace Orchards LLC to Upper Terrace Farms LLC.")
        )
        # The state is written canonical, and the line says what was saved.
        self.assertTrue(lines[2].endswith("State changed from OR to WA."), lines)
        # The stated change replaces "unchanged"; other sections' attestations are untouched.
        self.assertEqual(self.filing.sections_unchanged_attestation, {"practices_procedures": True})
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Upper Terrace Farms LLC")

    def test_the_records_own_validators_run_and_nothing_is_half_written(self):
        res = self._post(
            _all_correct(
                responsible_person={"status": "changed", "value": "Luis Ortega"},
                phone={"status": "changed", "value": "12345"},
            )
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone", res.json()["answers"])
        self.est.refresh_from_db()
        self.assertEqual(self.est.contact_person, "Laurel Brandt")
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.application_info_changes, "")

    def test_a_required_detail_cannot_be_removed(self):
        res = self._post(_all_correct(address={"status": "changed", "value": ""}))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.est.refresh_from_db()
        self.assertEqual(self.est.address, "1200 Orchard Rd")

    def test_removing_an_optional_detail_is_stated(self):
        self._post(_all_correct(trade_name={"status": "changed", "value": ""}))
        self.filing.refresh_from_db()
        self.assertTrue(self.filing.application_info_changes.endswith("Trade name (DBA) removed (was Upper Terrace)."))

    def test_changed_to_the_same_value_is_refused(self):
        res = self._post(_all_correct(city={"status": "changed", "value": "Hood River"}))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class RolesTests(_Step):
    def _member(self, role, email):
        user = User.objects.create_user(email=email, password="x", is_verified=True)
        WorksIn.objects.create(user=user, company=self.company, role=role)
        self.client.force_authenticate(user=user)
        return user

    def test_a_viewer_reads_but_cannot_answer(self):
        self._member(WorksIn.VIEWER, "vw@cd.test")
        got = self.client.get(self._url())
        self.assertEqual(got.status_code, status.HTTP_200_OK)
        self.assertFalse(got.json()["can_answer"])
        self.assertFalse(any(r["editable"] for r in got.json()["details"]))
        res = self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._post(_all_correct()).status_code, status.HTTP_403_FORBIDDEN)
        self.est.refresh_from_db()
        self.assertEqual(self.est.phone, "5415550111")
        self.filing.refresh_from_db()
        self.assertNotIn(APPLICATION_INFO_KEY, self.filing.sections_unchanged_attestation or {})

    def test_a_farm_manager_changes_the_farm_but_not_the_company(self):
        """The same split the record viewsets make: a farm edit is CA/FM, a company edit CA only."""
        self._member(WorksIn.FARM_MANAGER, "fm@cd.test")
        got = self.client.get(self._url()).json()
        editable = {r["key"]: r["editable"] for r in got["details"]}
        self.assertFalse(editable["legal_name"])
        self.assertTrue(editable["phone"])
        ok = self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}))
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content[:300])
        refused = self._post(_all_correct(legal_name={"status": "changed", "value": "Someone Else LLC"}))
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Upper Terrace Orchards LLC")

    def test_a_farm_manager_cannot_fill_an_empty_company_field_as_correct(self):
        """Recording a detail Trazo did not hold is still a write to the Company record (review of
        back #260): an empty trade name filled as "correct" needs the company admin role too, and
        must not leave "unchanged" set over a record that was just written."""
        Company.objects.filter(pk=self.company.pk).update(tradename=None)
        self._member(WorksIn.FARM_MANAGER, "fm2@cd.test")
        res = self._post(_all_correct(trade_name={"status": "correct", "value": "Some Other DBA"}))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.company.refresh_from_db()
        self.assertIsNone(self.company.tradename)
        self.filing.refresh_from_db()
        self.assertNotIn(APPLICATION_INFO_KEY, self.filing.sections_unchanged_attestation or {})


class RefusedAfterSigningTests(_Step):
    def test_a_signed_revision_refuses_the_step(self):
        sign = self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/{self.filing.pk}/sign/",
            {"signer_title": "Owner"},
            format="json",
        )
        self.assertEqual(sign.status_code, status.HTTP_200_OK, sign.content[:300])
        self.filing.refresh_from_db()
        signed_hash = self.filing.signed_content_sha256
        res = self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}))
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self._post(_all_correct()).status_code, status.HTTP_409_CONFLICT)
        self.est.refresh_from_db()
        self.assertEqual(self.est.phone, "5415550111")
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.content_sha256(), signed_hash)
        self.assertFalse(self.client.get(self._url()).json()["can_answer"])

    def test_a_filed_revision_refuses_the_step(self):
        self.filing.signed_at = datetime(2026, 8, 20, tzinfo=dt_tz.utc)
        self.filing.submitted_at = datetime(2026, 8, 21, tzinfo=dt_tz.utc)
        self.filing.save()
        self.assertEqual(self._post(_all_correct()).status_code, status.HTTP_409_CONFLICT)

    def test_a_farm_edit_after_signing_does_not_alter_the_filing(self):
        self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}))
        self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/{self.filing.pk}/sign/",
            {"signer_title": "Owner"},
            format="json",
        )
        self.filing.refresh_from_db()
        signed_hash = self.filing.signed_content_sha256
        sentence = _application_info_sentence(self.filing)
        # Edited elsewhere, through the farm's own endpoint, after the signature.
        edit = self.client.patch(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/",
            {"phone": "(541) 555-0222"},
            format="json",
        )
        self.assertEqual(edit.status_code, status.HTTP_200_OK, edit.content[:300])
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.content_sha256(), signed_hash)
        self.assertEqual(_application_info_sentence(self.filing), sentence)
        self.assertIn("555-0199", sentence)


class TenancyTests(_Step):
    def setUp(self):
        super().setUp()
        self.other_admin = User.objects.create_user(email="other@cd.test", password="x", is_verified=True)
        self.other = Company.objects.create(name="Other Co")
        WorksIn.objects.create(user=self.other_admin, company=self.other, role=WorksIn.COMPANY_ADMIN)
        self.other_est = Establishment.objects.create(name="Other Farm", company=self.other, phone="5095550100")
        other_osp = OrganicSystemPlan.objects.create(establishment=self.other_est, version_number=1, status="active")
        self.other_filing = OSPAnnualUpdate.objects.create(prior_osp=other_osp, reporting_year=2026)

    def test_another_companys_filing_through_its_own_url_is_refused(self):
        res = self._post(
            _all_correct(phone={"status": "changed", "value": "(541) 555-0199"}),
            filing=self.other_filing,
            company=self.other,
            est=self.other_est,
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.other_est.refresh_from_db()
        self.assertEqual(self.other_est.phone, "5095550100")

    def test_another_companys_filing_through_my_url_is_not_found(self):
        res = self._post(_all_correct(phone={"status": "changed", "value": "(541) 555-0199"}), filing=self.other_filing)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.other_est.refresh_from_db()
        self.assertEqual(self.other_est.phone, "5095550100")

    def test_a_payload_cannot_name_another_record(self):
        """No record id is accepted: the farm and company written are the filing's own. A key
        that is not a detail is refused at field level, before any record is touched."""
        body = _all_correct(phone={"status": "changed", "value": "(541) 555-0199"})
        body["answers"]["establishment"] = {"status": "changed", "value": str(self.other_est.pk)}
        body["establishment"] = self.other_est.pk
        body["company"] = self.other.pk
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        del body["answers"]["establishment"]
        ok = self._post(body)
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content[:300])
        self.est.refresh_from_db()
        self.other_est.refresh_from_db()
        self.assertEqual(self.est.phone, "(541) 555-0199")
        self.assertEqual(self.other_est.phone, "5095550100")
