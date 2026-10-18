"""A setup operator records a grower's records; it is never named as the producer.

Certifier handoff rehearsal, 2026-10-18 (finding H-1): on the assisted-setup pilot the audit
dossier's Producer Attestation printed "Producer / Operator: Oscar Munoz (Trazo setup)", the
account Trazo typed the grower's binder in with. The season and the plan were both created by
that account and the farm profile named no contact person, so every fallback landed on it.
§ 205.201(a) makes the producer the author.

Three places pick that name, and all three are pinned here: the dossier attestation, the renewal
packet cover's "Responsible person", and the default signer of an annual update. The last is the
one that would have done lasting harm: a grower signing would have frozen a revision under the
operator's name.
"""

import io
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

import reportlab.platypus as platypus
from pdfminer.high_level import extract_text

from carbon.models import CropType
from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.annual_update_filing import default_signer_name
from certifications.services.osp_module_pdf import _packet_cover_pdf, _renewal_context
from company.models import Company, Establishment
from history.models import History
from history.services import audit_export_service as audit_mod
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from subscriptions.pilot_operator import is_setup_operator, operator_last_name
from users.models import User


def _pdf_text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _AssistedSetupFarm(TestCase):
    """The rehearsal's shape: the operator created the season and the plan, no contact person."""

    def setUp(self):
        self.operator = User.objects.create_user(
            email="oscar+farm@trazo.test", password="x", first_name="Oscar", last_name=operator_last_name("Munoz")
        )
        self.grower = User.objects.create_user(
            email="grower@farm.test", password="x", first_name="John", last_name="Doe"
        )
        company = Company.objects.create(name="Assisted Co")
        self.est = Establishment.objects.create(name="Test Block", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.operator
        )


class IsSetupOperatorTests(TestCase):
    def test_only_an_account_carrying_the_setup_suffix_is_a_setup_operator(self):
        operator = User(first_name="Oscar", last_name=operator_last_name("Munoz"))
        grower = User(first_name="John", last_name="Doe")
        self.assertTrue(is_setup_operator(operator))
        self.assertFalse(is_setup_operator(grower))
        self.assertFalse(is_setup_operator(None))


class AttestationTests(_AssistedSetupFarm):
    def setUp(self):
        super().setUp()
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=6.0)
        crop = CropType.objects.create(
            name="Apples",
            slug="apples-setup-operator",
            category="tree_fruit",
            description="n",
            typical_farm_size="10",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.history = History.objects.create(
            parcel=parcel,
            product=Product.objects.create(name="Apples"),
            crop_type=crop,
            operator=self.operator,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _attestation_text(self):
        captured = []
        orig = platypus.Paragraph

        def spy(text, *a, **kw):
            captured.append(str(text))
            return orig(text, *a, **kw)

        platypus.Paragraph = spy
        audit_mod.Paragraph = spy
        try:
            AuditExportService(self.history, certification_type="organic")._build_producer_attestation_section()
        finally:
            platypus.Paragraph = orig
            audit_mod.Paragraph = orig
        return "\n".join(captured)

    def test_the_setup_operator_is_not_printed_as_the_producer(self):
        text = self._attestation_text()
        self.assertNotIn("Trazo setup", text)
        self.assertIn("(operator not set)", text)

    def test_the_contact_person_is_still_named(self):
        self.est.contact_person = "John Doe"
        self.est.save(update_fields=["contact_person"])
        text = self._attestation_text()
        self.assertIn("John Doe", text)
        self.assertNotIn("Trazo setup", text)

    def test_a_season_operator_who_is_the_grower_is_still_named(self):
        History.objects.filter(pk=self.history.pk).update(operator=self.grower)
        self.history.refresh_from_db()
        self.assertIn("John Doe", self._attestation_text())


class PacketCoverTests(_AssistedSetupFarm):
    def test_the_setup_operator_is_not_the_responsible_person(self):
        self.assertEqual(_renewal_context(self.osp)["responsible_person"], "")

    def test_the_cover_states_no_name_without_calling_it_the_plan_author(self):
        cover = _pdf_text(_packet_cover_pdf(self.osp))
        self.assertNotIn("Trazo setup", cover)
        self.assertNotIn("plan author", cover)
        self.assertIn("None is stated in Trazo: set the contact person on the farm profile.", cover)

    def test_a_grower_who_wrote_the_plan_is_still_the_fallback(self):
        OrganicSystemPlan.objects.filter(pk=self.osp.pk).update(created_by=self.grower)
        self.osp.refresh_from_db()
        self.assertEqual(_renewal_context(self.osp)["responsible_person"], "John Doe")
        self.assertIn("plan author", _pdf_text(_packet_cover_pdf(self.osp)))


class DefaultSignerTests(_AssistedSetupFarm):
    def _filing(self):
        return OSPAnnualUpdate.objects.create(prior_osp=self.osp, reporting_year=2027, changes_summary="Draft.")

    def test_the_grower_signing_is_the_signer_not_the_operator_who_wrote_the_plan(self):
        self.assertEqual(default_signer_name(self._filing(), self.grower), "John Doe")

    def test_the_contact_person_still_wins(self):
        Establishment.objects.filter(pk=self.est.pk).update(contact_person="Laurel Brandt")
        self.osp.refresh_from_db()
        self.assertEqual(default_signer_name(self._filing(), self.grower), "Laurel Brandt")
