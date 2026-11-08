"""WSDA's Additional Facilities and Third-Parties (AGR 2519, R 01/24) on the copy sheet.

AGR 2121 §J 13, §K 1 and §L 1 ask whether another operation takes the crop to a facility, stores it or
custom handles it, and a Yes is answered by attaching AGR 2519 for that facility. The form is WSDA's, filed
with WSDA, one per facility. The copy sheet gives, per facility another operation runs, every value Trazo
holds and names what the record leaves empty. It never ticks a box on the form.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from rest_framework.exceptions import ValidationError

from certifications.facility_activities import ACTIVITY_GROUPS, ACTIVITY_KEYS, ACTIVITY_LABELS
from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.serializers import PostHarvestFacilitySerializer
from certifications.services.agent_form_sheet import agent_form_sheet
from company.models import Company, Establishment

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"


class TheFormsActivities(SimpleTestCase):
    def test_seventeen_activities_in_the_forms_four_groups(self):
        self.assertEqual(len(ACTIVITY_KEYS), 17)
        self.assertEqual(
            [group for group, _items in ACTIVITY_GROUPS],
            ["general", "production", "potentially_exempt", "requires_certification"],
        )

    def test_labels_are_the_forms_words(self):
        self.assertEqual(ACTIVITY_LABELS["presizing_sorting_hydrocooling"], "Pre-sizing, sorting, hydrocooling crops")
        self.assertEqual(ACTIVITY_LABELS["bulk_storage"], "Storage of bulk, unpackaged organic products")
        self.assertEqual(ACTIVITY_LABELS["storage_packaged"], "Storage, cross-docking packaged products")


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Ridge Orchards LLC")
        self.est = Establishment.objects.create(name="Ridge Orchards", company=self.company, state="WA")

    def facility(self, **fields):
        return PostHarvestFacility.objects.create(
            establishment=self.est, name=fields.pop("name", "Valley Cold Storage"), **fields
        )

    def sheet(self, certifier=WSDA):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
        )
        return agent_form_sheet(osp)

    def row(self, item, certifier=WSDA):
        return next(r for r in self.sheet(certifier)["rows"] if r["item"] == item)


class SerializerTests(_Farm):
    def save(self, instance=None, **data):
        serializer = PostHarvestFacilitySerializer(instance=instance, data=data, partial=instance is not None)
        serializer.is_valid(raise_exception=True)
        return serializer.save(establishment=self.est) if instance is None else serializer.save()

    def test_activities_are_kept_in_the_forms_order_once_each(self):
        facility = self.save(
            name="Packer", activities=["bulk_storage", "presizing_sorting_hydrocooling", "bulk_storage"]
        )
        self.assertEqual(facility.activities, ["presizing_sorting_hydrocooling", "bulk_storage"])

    def test_an_activity_the_form_does_not_print_is_refused(self):
        with self.assertRaises(ValidationError):
            self.save(name="Packer", activities=["hulling"])

    def test_an_own_facility_has_no_exemption_to_explain(self):
        with self.assertRaises(ValidationError):
            self.save(name="Our shed", operated_by="this_operation", exemption_basis="Retail only")

    def test_switching_to_own_clears_a_stated_exemption(self):
        facility = self.facility(exemption_basis="Packaged product only")
        facility = self.save(instance=facility, operated_by="this_operation")
        self.assertEqual(facility.exemption_basis, "")


class CopySheetTests(_Farm):
    def test_a_certified_third_party_reads_its_record(self):
        self.facility(
            name="Valley Cold Storage",
            address="400 Cold Storage Rd",
            city="Wenatchee",
            state="WA",
            postal_code="98801",
            certification_number="WSDA-1234",
            certifier_name="WSDA",
            cert_document=SimpleUploadedFile("cert.pdf", b"%PDF-1.4 cert"),
            activities=["presizing_sorting_hydrocooling", "bulk_storage"],
            products_detail="Honeycrisp, bulk bins",
        )
        row = self.row("facilities_2519")
        self.assertEqual(row["kind"], "value")
        self.assertEqual(row["extra"]["business_name"], "Ridge Orchards LLC")
        (facility,) = row["value"]
        self.assertEqual(facility["name"], "Valley Cold Storage")
        self.assertEqual(facility["postal_code"], "98801")
        self.assertEqual(facility["activities"], ["presizing_sorting_hydrocooling", "bulk_storage"])
        self.assertEqual(facility["responsibility"], "certified_third_party")
        self.assertEqual(facility["certificate"], {"number": "WSDA-1234", "certifier": "WSDA", "copy_on_file": True})
        self.assertEqual(facility["missing"], [])

    def test_an_uncertified_third_party_carries_its_exemption_or_says_it_is_missing(self):
        facility = self.facility(name="Harbor Brokers", city="Seattle", state="WA")
        (entry,) = self.row("facilities_2519")["value"]
        self.assertEqual(entry["responsibility"], "uncertified_third_party")
        self.assertIsNone(entry["certificate"])
        self.assertEqual(entry["missing"], ["address", "postal_code", "activities", "description", "exemption_basis"])
        facility.exemption_basis = "Handles only sealed retail cartons (§ 205.101(e))"
        facility.save()
        (entry,) = self.row("facilities_2519")["value"]
        self.assertEqual(entry["exemption_basis"], "Handles only sealed retail cartons (§ 205.101(e))")
        self.assertNotIn("exemption_basis", entry["missing"])

    def test_own_facilities_are_named_not_listed(self):
        self.facility(name="Home packing shed", operated_by="this_operation")
        row = self.row("facilities_2519")
        self.assertEqual(row["kind"], "note")
        self.assertEqual(row["extra"]["reason"], "none_on_file")
        self.assertEqual(row["extra"]["own_facilities"], ["Home packing shed"])
        self.assertIsNone(row["value"])

    def test_the_sheet_never_ticks_the_responsibility_statement(self):
        self.facility(name="Harbor Brokers")
        self.assertEqual(self.row("facilities_2519_comments")["kind"], "yours")
        (entry,) = self.row("facilities_2519")["value"]
        self.assertNotIn("ticked", entry)
        self.assertIn(entry["responsibility"], ("certified_third_party", "uncertified_third_party"))

    def test_only_wsda_s_sheet_carries_it(self):
        self.facility(name="Valley Cold Storage")
        items = {r["item"] for r in self.sheet(CCOF)["rows"]}
        self.assertNotIn("facilities_2519", items)


class RegisterTests(SimpleTestCase):
    def test_the_form_is_registered_and_no_longer_a_gap(self):
        from certifications.services.certifier_register import load_forms

        forms = {f.document_id: f for f in load_forms("wsda")}
        self.assertIn("AGR 2519", forms)
        self.assertEqual(forms["AGR 2519"].revision, "R 01/24")
        from pathlib import Path

        scope = (Path(forms["AGR 2519"].path).parents[1] / "scope.yaml").read_text()
        self.assertNotIn("AGR 2519", scope)

    def test_the_three_rows_that_attach_it_are_covered(self):
        from certifications.services.certifier_register import load_forms

        forms = load_forms("wsda")
        for code, ref in (("J", "13"), ("K", "1"), ("L", "1")):
            form = next(f for f in forms if f.path.stem.startswith(f"2121-{code}-"))
            row = next(i for i in form.items if i.ref == ref)
            self.assertEqual(row.status, "covered", (code, ref))


class OnTheModulePage(_Farm):
    def page(self):
        import io

        from pdfminer.high_level import extract_text

        from certifications.services.osp_module_pdf import generate_module_pdf

        answers = {"handled_by_another_operation": {"value": "yes_uncertified"}}
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=99,
            status="draft",
            module_responses={"schema_version": 1, "modules": {"g6_1_harvest_transport": {"answers": answers}}},
        )
        data = generate_module_pdf(osp, "g6_1_harvest_transport")
        return " ".join(extract_text(io.BytesIO(data)).split())

    def test_the_handler_table_prints_the_activities_zip_and_stated_exemption(self):
        self.facility(
            name="Harbor Brokers",
            city="Seattle",
            state="WA",
            postal_code="98101",
            activities=["brokering_packaged", "storage_packaged"],
            exemption_basis="Handles only sealed retail cartons",
        )
        text = self.page()
        self.assertIn("Seattle, WA, 98101", text)
        self.assertIn(
            "Activities at this facility: Brokering or marketing packaged products; Storage, cross-docking packaged "
            "products.",
            text,
        )
        self.assertIn(
            "How the operation states it is exempt from certification (§ 205.101): Handles only sealed retail cartons",
            text,
        )

    def test_a_certified_facility_prints_no_exemption(self):
        self.facility(name="Valley Cold Storage", certification_number="WSDA-1234", exemption_basis="stale text")
        self.assertNotIn("exempt from certification", self.page())
