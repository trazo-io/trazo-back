"""Saved applicators: typed once, copied onto each spray, never linked from it (2026-11-12).

WAC 16-228-1320(1)(l) asks a spray record for the licensed applicator's full name, license number,
complete address and telephone number. Slice 3 put the address and phone on `ChemicalEvent` as plain
text, which meant typing them on every spray. `/api/companies/<id>/applicators/` keeps them once per
company; the spray form copies them onto the record, and the record keeps its copy whatever happens
to the saved row later (owner decision 2026-11-11).

What this pins: the model and its lengths, read and write by role, tenancy (another company's
applicator answers exactly like a missing one; the company comes from the URL, never the body),
deactivate instead of delete, the copy surviving a later edit, and the closure export and delete.
None of this reads the sibling repository.
"""

import io
import shutil
import tempfile
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from backend.storage import private_records_storage
from common.services import account_closure
from company.models import Applicator, Company, Establishment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, History
from product.models import Parcel, Product
from users.models import User, WorksIn

PROFILE = {
    "full_name": "Rosa Delgado",
    "license_number": "WA-58213",
    "license_state": "WA",
    "address": "12 Orchard Lane, Wenatchee, WA 98801",
    "phone": "509-555-0142",
}


def _member(company, email, role):
    user = User.objects.create_user(email=email, password="x")
    WorksIn.objects.create(user=user, company=company, role=role)
    return user


class _Orchards(TestCase):
    """Two fictional companies, each with an admin; the first also has a manager and a viewer."""

    def setUp(self):
        self.company = Company.objects.create(name="Fictional Bench Orchards")
        self.admin = _member(self.company, "admin@bench.example", WorksIn.COMPANY_ADMIN)
        self.manager = _member(self.company, "manager@bench.example", WorksIn.FARM_MANAGER)
        self.viewer = _member(self.company, "viewer@bench.example", WorksIn.VIEWER)

        self.other = Company.objects.create(name="Fictional River Orchards")
        self.other_admin = _member(self.other, "admin@river.example", WorksIn.COMPANY_ADMIN)
        self.theirs = Applicator.objects.create(company=self.other, full_name="Their Applicator", phone="509-555-0199")

        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user)
        return self.client

    def url(self, suffix="", company=None):
        return f"/api/companies/{(company or self.company).pk}/applicators/{suffix}"

    def _create(self, user=None, **fields):
        response = self._as(user or self.admin).post(self.url(), {**PROFILE, **fields}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return Applicator.objects.get(pk=response.json()["id"])


class ApplicatorModelTests(TestCase):
    def test_defaults_active_with_optional_license_and_contact(self):
        company = Company.objects.create(name="Fictional Defaults")
        applicator = Applicator.objects.create(company=company, full_name="Ana Ruiz")
        self.assertTrue(applicator.is_active)
        for name in ("license_number", "license_state", "address", "phone"):
            self.assertEqual(getattr(applicator, name), "", name)
        self.assertIsNotNone(applicator.created_at)
        self.assertIsNotNone(applicator.updated_at)

    def test_every_copied_value_fits_the_record_column_it_is_copied_into(self):
        """A profile value longer than its record column would be refused, or cut, at save."""
        for profile_field, record_field in (
            ("full_name", "applicator_name"),
            ("license_number", "applicator_certification"),
            ("address", "applicator_address"),
            ("phone", "applicator_phone"),
        ):
            with self.subTest(profile_field):
                self.assertLessEqual(
                    Applicator._meta.get_field(profile_field).max_length,
                    ChemicalEvent._meta.get_field(record_field).max_length,
                )

    def test_a_spray_record_never_links_to_a_saved_applicator(self):
        """The record keeps text copies. A relation would let a later profile edit rewrite the past."""
        related = [
            f.name
            for f in ChemicalEvent._meta.get_fields()
            if getattr(f, "related_model", None) is Applicator
            or getattr(getattr(f, "remote_field", None), "model", None) is Applicator
        ]
        self.assertEqual(related, [])
        # Nothing anywhere points at a saved applicator: no reverse relation exists on it.
        self.assertEqual(
            [f.name for f in Applicator._meta.get_fields() if f.auto_created and not f.concrete],
            [],
            "a model now points at Applicator; records keep text copies, never a link",
        )

    def test_active_rows_list_first_then_by_name(self):
        company = Company.objects.create(name="Fictional Order")
        Applicator.objects.create(company=company, full_name="Zoe", is_active=False)
        Applicator.objects.create(company=company, full_name="Bea")
        Applicator.objects.create(company=company, full_name="Ana")
        self.assertEqual(
            list(Applicator.objects.filter(company=company).values_list("full_name", flat=True)),
            ["Ana", "Bea", "Zoe"],
        )


class ApplicatorRoleTests(_Orchards):
    def test_admin_and_manager_add_edit_and_deactivate(self):
        for user in (self.admin, self.manager):
            with self.subTest(user=user.email):
                applicator = self._create(user, full_name=f"Applicator of {user.email}")
                self.assertEqual(applicator.company, self.company)
                self.assertEqual(applicator.address, PROFILE["address"])

                response = self._as(user).patch(self.url(f"{applicator.pk}/"), {"phone": "509-555-0100"}, format="json")
                self.assertEqual(response.status_code, 200, response.content)
                applicator.refresh_from_db()
                self.assertEqual(applicator.phone, "509-555-0100")

                response = self._as(user).delete(self.url(f"{applicator.pk}/"))
                self.assertEqual(response.status_code, 200, response.content)
                applicator.refresh_from_db()
                self.assertFalse(applicator.is_active)

    def test_viewer_reads_and_cannot_write(self):
        applicator = self._create()
        client = self._as(self.viewer)
        listed = client.get(self.url())
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([row["id"] for row in listed.json()], [applicator.pk])
        self.assertEqual(client.get(self.url(f"{applicator.pk}/")).status_code, 200)

        self.assertEqual(client.post(self.url(), PROFILE, format="json").status_code, 403)
        self.assertEqual(
            client.patch(self.url(f"{applicator.pk}/"), {"phone": "509-555-0000"}, format="json").status_code, 403
        )
        self.assertEqual(client.delete(self.url(f"{applicator.pk}/")).status_code, 403)

        applicator.refresh_from_db()
        self.assertEqual(applicator.phone, PROFILE["phone"])
        self.assertTrue(applicator.is_active)
        self.assertEqual(Applicator.objects.filter(company=self.company).count(), 1)

    def test_signed_out_is_refused(self):
        applicator = self._create()
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url()).status_code, (401, 403))
        self.assertIn(self.client.get(self.url(f"{applicator.pk}/")).status_code, (401, 403))


class ApplicatorTenancyTests(_Orchards):
    def test_another_companys_applicator_is_the_same_404_as_a_missing_one(self):
        """Through the caller's own company URL, a foreign id and an unused id answer identically."""
        missing = Applicator.objects.order_by("-pk").first().pk + 1000
        client = self._as(self.admin)
        for method, body in (("get", None), ("patch", {"full_name": "Taken"}), ("delete", None)):
            with self.subTest(method=method):
                call = getattr(client, method)
                kwargs = {"format": "json"} if body is not None else {}
                args = (body,) if body is not None else ()
                foreign = call(self.url(f"{self.theirs.pk}/"), *args, **kwargs)
                absent = call(self.url(f"{missing}/"), *args, **kwargs)
                self.assertEqual(foreign.status_code, 404)
                self.assertEqual((foreign.status_code, foreign.json()), (absent.status_code, absent.json()))

        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.full_name, "Their Applicator")
        self.assertTrue(self.theirs.is_active)

    def test_list_holds_only_the_url_companys_rows(self):
        mine = self._create()
        rows = self._as(self.admin).get(self.url()).json()
        self.assertEqual([row["id"] for row in rows], [mine.pk])

    def test_another_company_reaches_nothing(self):
        """An outsider is refused before any row is looked up, so an existing id and a missing one
        answer alike."""
        mine = self._create()
        missing = mine.pk + 1000
        client = self._as(self.other_admin)
        self.assertEqual(client.get(self.url()).status_code, 403)
        self.assertEqual(client.post(self.url(), PROFILE, format="json").status_code, 403)
        for method in ("get", "delete"):
            with self.subTest(method=method):
                existing = getattr(client, method)(self.url(f"{mine.pk}/"))
                absent = getattr(client, method)(self.url(f"{missing}/"))
                self.assertEqual(existing.status_code, 403)
                self.assertEqual((existing.status_code, existing.json()), (absent.status_code, absent.json()))
        response = client.patch(self.url(f"{mine.pk}/"), {"full_name": "Mine now"}, format="json")
        self.assertEqual(response.status_code, 403)

        mine.refresh_from_db()
        self.assertEqual(mine.full_name, PROFILE["full_name"])
        self.assertTrue(mine.is_active)
        self.assertEqual(Applicator.objects.filter(company=self.company).count(), 1)

    def test_company_in_the_body_is_ignored(self):
        applicator = self._create(company=self.other.pk)
        self.assertEqual(applicator.company, self.company)
        self.assertFalse(Applicator.objects.filter(company=self.other, full_name=PROFILE["full_name"]).exists())

        response = self._as(self.admin).patch(
            self.url(f"{applicator.pk}/"), {"company": self.other.pk, "phone": "509-555-0101"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        applicator.refresh_from_db()
        self.assertEqual(applicator.company, self.company)
        self.assertNotIn("company", response.json())


class ApplicatorDeactivateTests(_Orchards):
    def test_deactivate_keeps_the_row_and_takes_it_out_of_the_picker_list(self):
        kept = self._create(full_name="Ana Ruiz")
        gone = self._create(full_name="Beto Ruiz")
        client = self._as(self.admin)

        response = client.delete(self.url(f"{gone.pk}/"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        self.assertTrue(Applicator.objects.filter(pk=gone.pk).exists())

        picker = client.get(self.url(), {"active": "true"}).json()
        self.assertEqual([row["id"] for row in picker], [kept.pk])
        everyone = client.get(self.url()).json()
        self.assertEqual([(row["id"], row["is_active"]) for row in everyone], [(kept.pk, True), (gone.pk, False)])
        inactive = client.get(self.url(), {"active": "false"}).json()
        self.assertEqual([row["id"] for row in inactive], [gone.pk])

        # Deactivating twice is harmless, and turning the person back on is a PATCH.
        self.assertEqual(client.delete(self.url(f"{gone.pk}/")).status_code, 200)
        response = client.patch(self.url(f"{gone.pk}/"), {"is_active": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(client.get(self.url(), {"active": "true"}).json()), 2)

    def test_an_unreadable_active_filter_is_refused_not_ignored(self):
        response = self._as(self.admin).get(self.url(), {"active": "yes"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("active", response.json())


class ApplicatorValidationTests(_Orchards):
    def test_name_is_required(self):
        client = self._as(self.admin)
        for body in ({**PROFILE, "full_name": ""}, {**PROFILE, "full_name": "   "}, {"phone": "509-555-0142"}):
            with self.subTest(body=body):
                response = client.post(self.url(), body, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("full_name", response.json())

    def test_license_and_contact_are_optional(self):
        applicator = self._create(license_number="", license_state="", address="", phone="")
        self.assertEqual(applicator.license_number, "")

    def test_license_state_is_a_two_letter_us_code_stored_upper_case(self):
        self.assertEqual(self._create(license_state="or").license_state, "OR")
        client = self._as(self.admin)
        for value in ("XX", "Washington", "W"):
            with self.subTest(value=value):
                response = client.post(self.url(), {**PROFILE, "license_state": value}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("license_state", response.json())

    def test_values_are_trimmed(self):
        applicator = self._create(full_name="  Rosa Delgado  ", phone=" 509-555-0142 ")
        self.assertEqual((applicator.full_name, applicator.phone), ("Rosa Delgado", "509-555-0142"))


class RecordKeepsItsCopyTests(_Orchards):
    """The spray form copies the profile into the record's own fields; nothing ties them after."""

    def test_editing_or_deactivating_the_profile_leaves_a_saved_spray_unchanged(self):
        farm = Establishment.objects.create(name="Fictional Bench", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="North Block", establishment=farm, area=4.0)
        season = History.objects.create(
            name="Honeycrisp 2026",
            parcel=parcel,
            product=Product.objects.create(name="Apples"),
            operator=self.admin,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
        )
        applicator = self._create()

        # What the spray form sends after the picker copied the profile. A stray link key is ignored.
        response = self._as(self.admin).post(
            "/api/events/",
            {
                "event_type": CHEMICAL_EVENT_TYPE,
                "history": season.pk,
                "parcels": [parcel.pk],
                "date": "2026-05-02T06:30",
                "type": "PE",
                "commercial_name": "Entrust SC",
                "application_method": "air_blast",
                "volume_unit": "fl_oz",
                "area_unit": "acres",
                "applicator": applicator.pk,
                "applicator_name": applicator.full_name,
                "applicator_certification": applicator.license_number,
                "applicator_address": applicator.address,
                "applicator_phone": applicator.phone,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        spray = ChemicalEvent.objects.get(pk=response.json()["id"])
        copied = ("applicator_name", "applicator_certification", "applicator_address", "applicator_phone")
        before = {name: getattr(spray, name) for name in copied}
        self.assertEqual(
            before,
            {
                "applicator_name": PROFILE["full_name"],
                "applicator_certification": PROFILE["license_number"],
                "applicator_address": PROFILE["address"],
                "applicator_phone": PROFILE["phone"],
            },
        )

        client = self._as(self.admin)
        response = client.patch(
            self.url(f"{applicator.pk}/"),
            {
                "full_name": "Rosa Delgado-Ortiz",
                "license_number": "WA-99999",
                "address": "400 Valley Road, Yakima, WA 98901",
                "phone": "509-555-0177",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(client.delete(self.url(f"{applicator.pk}/")).status_code, 200)

        spray.refresh_from_db()
        self.assertEqual({name: getattr(spray, name) for name in copied}, before)


MEDIA = tempfile.mkdtemp(prefix="applicator-closure-test-")


@override_settings(MEDIA_ROOT=MEDIA)
class ApplicatorsLeaveWithTheCompanyTests(TestCase):
    """`close_account` exports the saved applicators, then deletes them with the company."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.company = Company.objects.create(name="Fictional Closing Orchards")
        Establishment.objects.create(name="North Block", company=self.company)
        self.applicator = Applicator.objects.create(company=self.company, **PROFILE)
        other = Company.objects.create(name="Fictional Staying Orchards")
        self.staying = Applicator.objects.create(company=other, full_name="Stays Put")

    def _bundle(self):
        key = account_closure.export(self.company)
        with private_records_storage().open(key, "rb") as fh:
            return zipfile.ZipFile(io.BytesIO(fh.read()))

    def test_the_export_holds_the_applicators(self):
        text = self._bundle().read("applicators.csv").decode()
        header, *rows = text.strip().splitlines()
        self.assertIn("full_name", header)
        self.assertIn("license_number", header)
        self.assertEqual(len(rows), 1)
        self.assertIn(PROFILE["full_name"], rows[0])
        self.assertIn(PROFILE["phone"], rows[0])
        self.assertNotIn("Stays Put", text)

    def test_a_change_after_the_export_blocks_the_delete_and_apply_removes_the_rows(self):
        self.assertEqual(account_closure.plan(self.company).rows.get("company.Applicator"), 1)
        self._bundle()
        self.applicator.phone = "509-555-0000"
        self.applicator.save()
        with self.assertRaisesMessage(account_closure.ClosureRefused, "changed since the export"):
            account_closure.apply(self.company, confirm_name=self.company.name)
        self.assertTrue(Applicator.objects.filter(pk=self.applicator.pk).exists())

        self._bundle()
        with patch("fieldnotes.services.transcribe.delete_media", return_value=True):
            account_closure.apply(self.company, confirm_name=self.company.name)
        self.assertFalse(Applicator.objects.filter(pk=self.applicator.pk).exists())
        self.assertTrue(Applicator.objects.filter(pk=self.staying.pk).exists())
